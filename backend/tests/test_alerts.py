"""Threshold alerts: value math, firing/re-arm, webhook delivery, SSRF, scope."""

import csv
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.analytics.alerts import (
    AlertError, AlertNotFound, _compute_value, create_alert, delete_alert,
    evaluate_alert, list_alerts, send_test, set_enabled,
)
from app.core import config
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# Jan total 3000; Feb total 900 → MoM change = -70%
DATA = [["date", "branch", "revenue"],
        ["2025-01-05", "Delhi", "1000"],
        ["2025-01-06", "Mumbai", "2000"],
        ["2025-02-05", "Delhi", "500"],
        ["2025-02-06", "Mumbai", "400"]]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(DATA))
    return con, "ws_a", res.dataset_id


class _Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.posts.append(json.loads(self.rfile.read(length) or b"{}"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture()
def webhook():
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    server.posts = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _, port = server.server_address
    try:
        yield server, f"http://127.0.0.1:{port}/hook"
    finally:
        server.shutdown()


@pytest.fixture()
def allow_private(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_FETCH", True)


# --------------------------------------------------------- value math ------

def test_total_latest_mom(ds):
    con, ws, dsid = ds
    assert _compute_value(con, ws, dsid, "revenue", "total") == 3900.0
    assert _compute_value(con, ws, dsid, "revenue", "latest") == 900.0
    assert _compute_value(con, ws, dsid, "revenue", "mom_pct") == pytest.approx(-70.0)


# --------------------------------------------------------- validation ------

def test_create_validates(ds, allow_private, webhook):
    con, ws, dsid = ds
    _, url = webhook
    with pytest.raises(AlertError):  # not a measure
        create_alert(con, ws, dsid, "x", "branch", "total", "lt", 1, url)
    with pytest.raises(AlertError):  # bad aggregate
        create_alert(con, ws, dsid, "x", "revenue", "nonsense", "lt", 1, url)
    with pytest.raises(AlertError):  # bad comparator
        create_alert(con, ws, dsid, "x", "revenue", "total", "??", 1, url)


def test_create_rejects_private_webhook(ds):
    con, ws, dsid = ds  # allow_private NOT set → loopback refused
    with pytest.raises(AlertError):
        create_alert(con, ws, dsid, "x", "revenue", "total", "lt", 1, "http://127.0.0.1/hook")


# --------------------------------------------- fire, deliver, re-arm -------

def test_fires_once_then_dedupes_and_rearms(ds, allow_private, webhook):
    con, ws, dsid = ds
    server, url = webhook
    # MoM change is -70%; fire when it drops more than 50% (i.e. < -50)
    a = create_alert(con, ws, dsid, "Revenue crash", "revenue", "mom_pct", "lt", -50, url)

    r1 = evaluate_alert(con, ws, a["alert_id"])
    assert r1["state"] == "firing" and r1["fired"] is True
    assert len(server.posts) == 1
    assert server.posts[0]["value"] == pytest.approx(-70.0) and "text" in server.posts[0]

    # still firing → no second delivery
    evaluate_alert(con, ws, a["alert_id"])
    assert len(server.posts) == 1

    # relax the threshold so it's OK now (no delivery), then tighten again → re-fires
    con.execute("UPDATE alerts SET threshold = -90 WHERE alert_id = ?", [a["alert_id"]])
    assert evaluate_alert(con, ws, a["alert_id"])["state"] == "ok"
    assert len(server.posts) == 1
    con.execute("UPDATE alerts SET threshold = -50 WHERE alert_id = ?", [a["alert_id"]])
    assert evaluate_alert(con, ws, a["alert_id"])["fired"] is True
    assert len(server.posts) == 2


def test_not_firing_no_delivery(ds, allow_private, webhook):
    con, ws, dsid = ds
    server, url = webhook
    a = create_alert(con, ws, dsid, "High total", "revenue", "total", "gt", 999999, url)
    assert evaluate_alert(con, ws, a["alert_id"])["state"] == "ok"
    assert server.posts == []


def test_disabled_alert_does_not_deliver(ds, allow_private, webhook):
    con, ws, dsid = ds
    server, url = webhook
    a = create_alert(con, ws, dsid, "x", "revenue", "total", "gt", 0, url)
    set_enabled(con, ws, a["alert_id"], False)
    evaluate_alert(con, ws, a["alert_id"])
    assert server.posts == []


def test_send_test_posts(ds, allow_private, webhook):
    con, ws, dsid = ds
    server, url = webhook
    a = create_alert(con, ws, dsid, "x", "revenue", "total", "gt", 0, url)
    assert send_test(con, ws, a["alert_id"])["ok"] is True
    assert len(server.posts) == 1 and server.posts[0].get("test") is True


# --------------------------------------------------------- isolation -------

def test_alerts_workspace_scoped(ds, allow_private, webhook):
    con, ws, dsid = ds
    _, url = webhook
    a = create_alert(con, ws, dsid, "x", "revenue", "total", "gt", 0, url)
    assert list_alerts(con, "ws_b", dsid) == []
    with pytest.raises(AlertNotFound):
        set_enabled(con, "ws_b", a["alert_id"], False)
    assert delete_alert(con, "ws_b", a["alert_id"]) == 0
