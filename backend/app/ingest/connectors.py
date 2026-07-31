"""Live data sources — connect a URL / Google Sheet that stays in sync.

A *source* is a remote CSV endpoint (a public CSV URL or a Google Sheet)
attached to a dataset. Syncing fetches the latest data and refreshes the
dataset:

  FIRST SYNC   creates a brand-new dataset (auto-detected columns), exactly
               like a file upload.
  RE-SYNC      full-snapshot refresh of the *same* dataset_id (so the
               dashboard's selection never breaks) — the physical table is
               rebuilt from the latest fetch, and any user column-role
               overrides are preserved.

Security — the fetcher is the sensitive part, so it is hardened against
Server-Side Request Forgery (SSRF):

  * only http/https URLs are allowed;
  * the hostname is resolved and EVERY resolved IP must be a public address —
    private, loopback, link-local (incl. the 169.254.169.254 cloud-metadata
    endpoint), reserved, multicast and unspecified addresses are refused;
  * redirects are followed manually, and each hop is re-validated;
  * the response is size-capped while streaming.

  (Residual: validate-then-connect leaves a narrow DNS-rebinding TOCTOU
  window; acceptable for this trust level and documented here. Set
  IH_ALLOW_PRIVATE_FETCH=1 to intentionally allow internal URLs.)

Everything is workspace-scoped and admin-gated at the API layer; identifiers
still pass the same sanitize/whitelist path as uploads.
"""

import re

from ..analytics.detect import detect_schema
from ..analytics.engine import DatasetNotFound, get_dataset
from ..core import config, db, nettrust
from ..core.nettrust import BlockedURLError, FetchError
from ..core.security import new_id
from ..core.sqlsafe import quote_identifier, safe_table_name, sanitize_identifier
from .pipeline import _dedupe_columns, _read_structured, ingest_structured

SOURCE_KINDS = ("url_csv", "google_sheet")


class SourceError(ValueError):
    """A source could not be created, fetched, or parsed."""


class SourceNotFound(SourceError):
    """No such source in this workspace."""


# --------------------------------------------------------- URL handling ----

_SHEET_RE = re.compile(r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")


def normalize_url(kind: str, url: str) -> str:
    """Turn a Google Sheet 'edit'/share link into its CSV export URL.

    Any docs.google.com spreadsheet link is normalized (regardless of the
    declared kind), so users can paste the URL straight from the address bar.
    """
    m = _SHEET_RE.match(url.strip())
    if m and ("docs.google.com" in url):
        sheet_id = m.group(1)
        gid = re.search(r"[#?&]gid=(\d+)", url)
        gid = gid.group(1) if gid else "0"
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return url.strip()


def _validate_url(url: str, allow_private: bool | None = None) -> None:
    """SSRF policy for a source URL — delegates to the shared guard and
    surfaces failures as SourceError for the connector callers/tests."""
    try:
        nettrust.validate_url(url, allow_private)
    except BlockedURLError as exc:
        raise SourceError(str(exc))


def fetch_csv(url: str, max_bytes: int) -> bytes:
    """Fetch a remote CSV via the shared SSRF-guarded GET (size-capped)."""
    try:
        return nettrust.http_get(url, max_bytes)
    except (BlockedURLError, FetchError) as exc:
        raise SourceError(str(exc))


# --------------------------------------------------------- persistence ----

_SOURCE_KEYS = [
    "source_id", "dataset_id", "name", "kind", "url", "refresh_interval_minutes",
    "status", "last_error", "last_synced", "row_count", "created_at",
]
_SOURCE_SELECT = ", ".join(_SOURCE_KEYS)


def _row_to_source(row) -> dict:
    d = dict(zip(_SOURCE_KEYS, row))
    d["last_synced"] = str(d["last_synced"]) if d["last_synced"] is not None else None
    d["created_at"] = str(d["created_at"]) if d["created_at"] is not None else None
    return d


def _get_source(con, workspace_id: str, source_id: str) -> dict:
    row = con.execute(
        f"SELECT {_SOURCE_SELECT} FROM data_sources WHERE source_id = ? AND workspace_id = ?",
        [source_id, workspace_id],
    ).fetchone()
    if row is None:
        raise SourceNotFound("source not found")
    return _row_to_source(row)


def list_sources(con, workspace_id: str) -> list[dict]:
    rows = con.execute(
        f"SELECT {_SOURCE_SELECT} FROM data_sources WHERE workspace_id = ? ORDER BY created_at DESC",
        [workspace_id],
    ).fetchall()
    return [_row_to_source(r) for r in rows]


def create_source(con, workspace_id: str, name: str, kind: str, url: str,
                  refresh_interval_minutes: int = 0) -> dict:
    name = (name or "").strip()
    url = (url or "").strip()
    if not name:
        raise SourceError("a name is required")
    if kind not in SOURCE_KINDS:
        raise SourceError("unknown source type")
    if not url:
        raise SourceError("a URL is required")
    # validate scheme + host now for fast feedback; the real fetch is on sync
    _validate_url(normalize_url(kind, url))
    try:
        interval = int(refresh_interval_minutes or 0)
    except (TypeError, ValueError):
        interval = 0
    interval = max(0, min(interval, 7 * 24 * 60))  # clamp to [0, 1 week]
    source_id = new_id("src")
    con.execute(
        """INSERT INTO data_sources
           (source_id, workspace_id, name, kind, url, refresh_interval_minutes, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        [source_id, workspace_id, name, kind, url, interval],
    )
    return _get_source(con, workspace_id, source_id)


def delete_source(con, workspace_id: str, source_id: str) -> int:
    n = con.execute(
        "SELECT count(*) FROM data_sources WHERE source_id = ? AND workspace_id = ?",
        [source_id, workspace_id],
    ).fetchone()[0]
    con.execute("DELETE FROM data_sources WHERE source_id = ? AND workspace_id = ?",
                [source_id, workspace_id])
    return n


# ------------------------------------------------------------- syncing ----

def _safe_filename(name: str) -> str:
    stem = sanitize_identifier(name) or "source"
    return f"{stem}.csv"


def _refresh_existing_dataset(con, workspace_id: str, dataset_id: str, filename: str, content: bytes) -> int:
    """Full-snapshot refresh: rebuild the dataset's table from `content`,
    keeping the same dataset_id and preserving user column-role overrides."""
    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise SourceError("this source's dataset is not a structured dataset")
    tq = safe_table_name(dataset["table_name"])

    df = _read_structured(filename, content)
    if df.empty:
        raise SourceError("source returned no data rows")
    df.columns = _dedupe_columns([sanitize_identifier(c) for c in df.columns])
    profiles = detect_schema(df)

    overrides = {
        r[0]: (r[1], r[2])
        for r in con.execute(
            """SELECT column_name, role, subtype FROM dataset_columns
               WHERE dataset_id = ? AND workspace_id = ? AND overridden = true""",
            [dataset_id, workspace_id],
        ).fetchall()
    }

    batch_id = new_id("batch")
    con.register("_ih_src_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {tq} AS SELECT * FROM _ih_src_df")
    con.unregister("_ih_src_df")
    bc = quote_identifier(db.BATCH_COL)
    con.execute(f"ALTER TABLE {tq} ADD COLUMN {bc} VARCHAR")
    con.execute(f"UPDATE {tq} SET {bc} = ?", [batch_id])

    con.execute("DELETE FROM dataset_columns WHERE dataset_id = ? AND workspace_id = ?",
                [dataset_id, workspace_id])
    rows = []
    for p in profiles:
        if p.name in overrides:
            role, subtype = overrides[p.name]
            rows.append((dataset_id, workspace_id, p.name, role, subtype, p.distinct_count, True))
        else:
            rows.append((dataset_id, workspace_id, p.name, p.role, p.subtype, p.distinct_count, False))
    con.executemany(
        """INSERT INTO dataset_columns
           (dataset_id, workspace_id, column_name, role, subtype, distinct_count, overridden)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    # a snapshot refresh supersedes any prior append batches / archived rows
    con.execute("DELETE FROM ingest_batches WHERE dataset_id = ? AND workspace_id = ?",
                [dataset_id, workspace_id])
    con.execute("DELETE FROM row_archive WHERE dataset_id = ? AND workspace_id = ?",
                [dataset_id, workspace_id])
    con.execute(
        """INSERT INTO ingest_batches (batch_id, dataset_id, workspace_id, source_file, mode, rows_added)
           VALUES (?, ?, ?, ?, 'sync', ?)""",
        [batch_id, dataset_id, workspace_id, filename, len(df)],
    )
    con.execute(
        "UPDATE datasets SET row_count = ?, source_file = ?, ingested_at = current_timestamp "
        "WHERE dataset_id = ? AND workspace_id = ?",
        [len(df), filename, dataset_id, workspace_id],
    )
    return len(df)


def sync_source(con, workspace_id: str, source_id: str) -> dict:
    """Fetch the source and (create or refresh) its dataset. On failure the
    error is recorded on the source row and then re-raised."""
    src = _get_source(con, workspace_id, source_id)
    filename = _safe_filename(src["name"])
    try:
        content = fetch_csv(normalize_url(src["kind"], src["url"]), config.MAX_UPLOAD_BYTES)

        existing = None
        if src["dataset_id"]:
            try:
                existing = get_dataset(con, workspace_id, src["dataset_id"])
            except DatasetNotFound:
                existing = None

        if existing:
            rows = _refresh_existing_dataset(con, workspace_id, src["dataset_id"], filename, content)
            dataset_id = src["dataset_id"]
        else:
            res = ingest_structured(con, workspace_id, filename, content, src["name"])
            dataset_id, rows = res.dataset_id, res.row_count
    except (SourceError, ValueError) as exc:
        con.execute(
            "UPDATE data_sources SET status = 'error', last_error = ?, last_synced = current_timestamp "
            "WHERE source_id = ? AND workspace_id = ?",
            [str(exc)[:500], source_id, workspace_id],
        )
        raise

    con.execute(
        "UPDATE data_sources SET dataset_id = ?, status = 'ok', last_error = NULL, "
        "last_synced = current_timestamp, row_count = ? WHERE source_id = ? AND workspace_id = ?",
        [dataset_id, rows, source_id, workspace_id],
    )
    return {"source_id": source_id, "dataset_id": dataset_id, "row_count": rows, "status": "ok"}


def due_sources(con) -> list[tuple[str, str]]:
    """(source_id, workspace_id) for every source whose auto-refresh is due."""
    return con.execute(
        """SELECT source_id, workspace_id FROM data_sources
           WHERE refresh_interval_minutes > 0
             AND (last_synced IS NULL
                  OR last_synced < now() - to_minutes(refresh_interval_minutes))"""
    ).fetchall()
