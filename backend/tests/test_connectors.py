"""Live data-source connectors: SSRF guard, sync lifecycle, isolation, caps."""

import csv
import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.analytics.engine import compute_dashboard
from app.core import config
from app.ingest.connectors import (
    SourceError, SourceNotFound, _validate_url, create_source, fetch_csv,
    list_sources, normalize_url, sync_source,
)


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


JAN = [["date", "branch", "revenue"],
       ["2025-01-05", "Delhi", "1000"],
       ["2025-01-06", "Mumbai", "2000"]]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.server.csv_bytes
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture()
def http_csv():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.csv_bytes = _csv(JAN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _, port = server.server_address
    try:
        yield server, f"http://127.0.0.1:{port}/data.csv"
    finally:
        server.shutdown()


@pytest.fixture()
def ws(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    return "ws_a"


@pytest.fixture()
def allow_private(monkeypatch):
    # the local test server is on loopback; explicitly opt in for the fetch path
    monkeypatch.setattr(config, "ALLOW_PRIVATE_FETCH", True)


# --------------------------------------------------------- SSRF guard ------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",              # loopback
    "http://10.0.0.5/x",               # private
    "http://192.168.1.10/x",           # private
    "http://169.254.169.254/latest/",  # cloud metadata (link-local)
    "http://[::1]/x",                  # IPv6 loopback
])
def test_ssrf_blocks_internal_addresses(url):
    with pytest.raises(SourceError):
        _validate_url(url, allow_private=False)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/1"])
def test_ssrf_blocks_non_http_schemes(url):
    with pytest.raises(SourceError):
        _validate_url(url)


def test_ssrf_allows_public_ip():
    # literal public IP → no DNS/network needed, must not raise
    _validate_url("http://8.8.8.8/data.csv", allow_private=False)


# --------------------------------------------------- URL normalization -----

def test_google_sheet_url_normalized():
    got = normalize_url("google_sheet", "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=42")
    assert got == "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv&gid=42"


def test_google_sheet_without_gid_defaults_to_zero():
    got = normalize_url("google_sheet", "https://docs.google.com/spreadsheets/d/XYZ/edit")
    assert got.endswith("export?format=csv&gid=0")


def test_plain_url_is_unchanged():
    assert normalize_url("url_csv", "https://data.example.com/a.csv") == "https://data.example.com/a.csv"


# ----------------------------------------------------- create + guard ------

def test_create_rejects_private_url(con, ws):
    with pytest.raises(SourceError):
        create_source(con, "ws_a", "x", "url_csv", "http://127.0.0.1/a.csv")


def test_create_rejects_bad_scheme(con, ws):
    with pytest.raises(SourceError):
        create_source(con, "ws_a", "x", "url_csv", "file:///etc/passwd")


def test_create_rejects_unknown_kind(con, ws):
    with pytest.raises(SourceError):
        create_source(con, "ws_a", "x", "mystery", "https://data.example.com/a.csv")


# --------------------------------------------------------- sync flow -------

def test_first_sync_creates_dataset(con, ws, http_csv, allow_private):
    _, url = http_csv
    src = create_source(con, "ws_a", "Sales", "url_csv", url)
    res = sync_source(con, "ws_a", src["source_id"])
    assert res["status"] == "ok" and res["row_count"] == 2
    assert compute_dashboard(con, "ws_a", res["dataset_id"])["row_count_filtered"] == 2


def test_resync_refreshes_same_dataset(con, ws, http_csv, allow_private):
    server, url = http_csv
    src = create_source(con, "ws_a", "Sales", "url_csv", url)
    first = sync_source(con, "ws_a", src["source_id"])
    dsid = first["dataset_id"]

    # the source now serves an extra row → a re-sync reflects it, same dataset
    server.csv_bytes = _csv(JAN + [["2025-01-07", "Pune", "3000"]])
    second = sync_source(con, "ws_a", src["source_id"])
    assert second["dataset_id"] == dsid            # selection never breaks
    assert second["row_count"] == 3
    assert compute_dashboard(con, "ws_a", dsid)["row_count_filtered"] == 3


def test_resync_preserves_column_overrides(con, ws, http_csv, allow_private):
    server, url = http_csv
    src = create_source(con, "ws_a", "Sales", "url_csv", url)
    dsid = sync_source(con, "ws_a", src["source_id"])["dataset_id"]
    con.execute(
        "UPDATE dataset_columns SET role = 'ignored', overridden = true "
        "WHERE dataset_id = ? AND column_name = 'branch'", [dsid],
    )
    sync_source(con, "ws_a", src["source_id"])
    row = con.execute(
        "SELECT role, overridden FROM dataset_columns WHERE dataset_id = ? AND column_name = 'branch'",
        [dsid],
    ).fetchone()
    assert row == ("ignored", True)


def test_bad_source_records_error(con, ws, allow_private, monkeypatch):
    # a reachable-looking URL that fails to fetch marks the source 'error'
    src = create_source(con, "ws_a", "Broken", "url_csv", "http://127.0.0.1:1/none.csv")
    with pytest.raises(SourceError):
        sync_source(con, "ws_a", src["source_id"])
    s = list_sources(con, "ws_a")[0]
    assert s["status"] == "error" and s["last_error"]


# ------------------------------------------------------ isolation + cap ----

def test_source_is_workspace_scoped(con, ws, http_csv, allow_private):
    _, url = http_csv
    src = create_source(con, "ws_a", "S", "url_csv", url)
    sync_source(con, "ws_a", src["source_id"])
    assert list_sources(con, "ws_b") == []
    with pytest.raises(SourceNotFound):
        sync_source(con, "ws_b", src["source_id"])


def test_size_cap_enforced(http_csv, allow_private):
    _, url = http_csv
    with pytest.raises(SourceError):
        fetch_csv(url, max_bytes=5)
