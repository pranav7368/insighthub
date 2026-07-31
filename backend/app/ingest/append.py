"""Incremental ingestion — add a new file (e.g. next month's report) into an
existing structured dataset. Every case is handled explicitly:

  SCHEMA   exact match -> append; new column -> added (old rows NULL); missing
           column -> blank for new rows; no shared columns -> rejected.
  DEDUP    a row whose user-columns exactly match an existing row is skipped
           (re-uploading the same file is idempotent -> never double-counts).
  MODE     "append"          -> add the new rows.
           "replace_period"  -> for corrections: replace all existing rows in
                                the month range the new file covers (removed
                                rows are archived so a rollback restores them).
  UNDO     every append is a batch; rollback deletes its added rows and
           restores any rows it replaced.

Security: every identifier passes `safe_identifier` (whitelisted to the
dataset's real columns); values are bound params; admin-only; workspace-scoped.
The provenance column is internal and never exposed to detection/dashboards.
"""

import json

import pandas.api.types as pt

from ..analytics.detect import detect_column
from ..analytics.engine import DatasetNotFound, get_columns, get_dataset
from ..core import db
from ..core.security import new_id
from ..core.sqlsafe import quote_identifier, safe_identifier, safe_table_name, sanitize_identifier
from .pipeline import _dedupe_columns, _read_structured

BC = quote_identifier(db.BATCH_COL)


def _duckdb_type(series) -> str:
    if pt.is_bool_dtype(series):
        return "BOOLEAN"
    if pt.is_integer_dtype(series):
        return "BIGINT"
    if pt.is_float_dtype(series):
        return "DOUBLE"
    if pt.is_datetime64_any_dtype(series):
        return "TIMESTAMP"
    return "VARCHAR"


def _physical_columns(con, tq):
    return [r[0] for r in con.execute(f"DESCRIBE {tq}").fetchall()]


def _ensure_batch_column(con, tq):
    if db.BATCH_COL not in _physical_columns(con, tq):
        con.execute(f"ALTER TABLE {tq} ADD COLUMN {BC} VARCHAR")


def _hash_expr(cols, allowed, alias=""):
    # unit-separated, NUL-coalesced so distinct rows can't collide via NULLs
    parts = ",".join(
        f"coalesce(CAST({alias}{safe_identifier(c, allowed)} AS VARCHAR), chr(0))" for c in cols
    )
    return f"md5(concat_ws(chr(31), {parts}))"


def _month_expr(date_col, allowed):
    dq = safe_identifier(date_col, allowed)
    return f"strftime(date_trunc('month', TRY_CAST({dq} AS TIMESTAMP)), '%Y-%m')"


def append_to_dataset(con, workspace_id, dataset_id, filename, content, mode="append") -> dict:
    if mode not in ("append", "replace_period"):
        mode = "append"
    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DatasetNotFound(f"{dataset_id} is not a structured dataset")

    existing = [c.name for c in get_columns(con, workspace_id, dataset_id)]
    existing_set = set(existing)
    date_col = next((c.name for c in get_columns(con, workspace_id, dataset_id) if c.role == "date"), None)
    tq = safe_table_name(dataset["table_name"])

    df = _read_structured(filename, content)
    if df.empty:
        raise ValueError("file has no data rows")
    df.columns = _dedupe_columns([sanitize_identifier(c) for c in df.columns])
    incoming = list(df.columns)

    if not (existing_set & set(incoming)):
        raise ValueError("this file shares no columns with the dataset — upload it as a new dataset instead")

    new_cols = [c for c in incoming if c not in existing_set]
    missing_cols = [c for c in existing if c not in set(incoming)]
    warnings = []

    _ensure_batch_column(con, tq)

    # add any new columns (physical + metadata), so future rows can carry them
    for c in new_cols:
        con.execute(f"ALTER TABLE {tq} ADD COLUMN {quote_identifier(c)} {_duckdb_type(df[c])}")
        prof = detect_column(c, df[c])
        con.execute(
            """INSERT INTO dataset_columns (dataset_id, workspace_id, column_name, role, subtype, distinct_count, overridden)
               VALUES (?, ?, ?, ?, ?, ?, false)""",
            [dataset_id, workspace_id, prof.name, prof.role, prof.subtype, prof.distinct_count],
        )
        warnings.append(f"new column '{c}' added (detected as {prof.role})")
    if missing_cols:
        warnings.append("blank for new rows (not in this file): " + ", ".join(missing_cols))

    full_cols = existing + new_cols
    allowed = set(full_cols)
    for c in full_cols:                       # align incoming to the full column set
        if c not in df.columns:
            df[c] = None
    df = df[full_cols]

    batch_id = new_id("batch")
    con.register("_ih_incoming", df)
    before = con.execute(f"SELECT count(*) FROM {tq}").fetchone()[0]
    rows_removed, skipped = 0, 0
    effective_mode = mode

    insert_cols = ", ".join(quote_identifier(c) for c in full_cols) + f", {BC}"

    try:
        if mode == "replace_period" and date_col:
            mexpr = _month_expr(date_col, allowed)
            lo, hi = con.execute(f"SELECT min({mexpr}), max({mexpr}) FROM _ih_incoming").fetchone()
            if lo is not None:
                struct = "{" + ", ".join(f"'{c}': {safe_identifier(c, allowed)}" for c in full_cols) + "}"
                con.execute(
                    f"""INSERT INTO row_archive (batch_id, workspace_id, dataset_id, row_json)
                        SELECT ?, ?, ?, to_json({struct}) FROM {tq}
                        WHERE {mexpr} BETWEEN ? AND ?""",
                    [batch_id, workspace_id, dataset_id, lo, hi],
                )
                rows_removed = con.execute(
                    f"SELECT count(*) FROM {tq} WHERE {mexpr} BETWEEN ? AND ?", [lo, hi]
                ).fetchone()[0]
                con.execute(f"DELETE FROM {tq} WHERE {mexpr} BETWEEN ? AND ?", [lo, hi])
                warnings.append(f"replaced {rows_removed} existing row(s) for {lo}…{hi}")
            select_cols = ", ".join(safe_identifier(c, allowed) for c in full_cols)
            con.execute(f"INSERT INTO {tq} ({insert_cols}) SELECT {select_cols}, ? FROM _ih_incoming", [batch_id])
        else:
            if mode == "replace_period":
                effective_mode = "append"
                warnings.append("no date column — added as new rows instead of replacing")
            incoming_total = len(df)
            hi_in = _hash_expr(existing, allowed, "i.")
            h_tab = _hash_expr(existing, allowed, "t.")
            select_cols = ", ".join("i." + safe_identifier(c, allowed) for c in full_cols)
            con.execute(
                f"""INSERT INTO {tq} ({insert_cols})
                    SELECT {select_cols}, ? FROM _ih_incoming i
                    WHERE {hi_in} NOT IN (SELECT {h_tab} FROM {tq} t)""",
                [batch_id],
            )
            added_now = con.execute(f"SELECT count(*) FROM {tq}").fetchone()[0] - before
            skipped = incoming_total - added_now
            if skipped:
                warnings.append(f"skipped {skipped} row(s) already present (duplicate)")
    finally:
        con.unregister("_ih_incoming")

    after = con.execute(f"SELECT count(*) FROM {tq}").fetchone()[0]
    rows_added = after - (before - rows_removed)

    con.execute(
        """INSERT INTO ingest_batches
           (batch_id, dataset_id, workspace_id, source_file, mode, rows_added, rows_removed, skipped_dupes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [batch_id, dataset_id, workspace_id, filename, effective_mode, rows_added, rows_removed, skipped],
    )
    con.execute("UPDATE datasets SET row_count = ? WHERE dataset_id = ? AND workspace_id = ?",
                [after, dataset_id, workspace_id])

    return {
        "batch_id": batch_id, "mode": effective_mode, "rows_added": rows_added,
        "rows_removed": rows_removed, "skipped_duplicates": skipped,
        "new_columns": new_cols, "missing_columns": missing_cols,
        "row_count": after, "warnings": warnings,
    }


def list_batches(con, workspace_id, dataset_id) -> list[dict]:
    rows = con.execute(
        """SELECT batch_id, source_file, mode, rows_added, rows_removed, skipped_dupes, created_at
           FROM ingest_batches WHERE dataset_id = ? AND workspace_id = ? ORDER BY created_at DESC""",
        [dataset_id, workspace_id],
    ).fetchall()
    keys = ["batch_id", "source_file", "mode", "rows_added", "rows_removed", "skipped_dupes", "created_at"]
    return [{**dict(zip(keys, r)), "created_at": str(r[6])} for r in rows]


def rollback_batch(con, workspace_id, dataset_id, batch_id) -> dict:
    dataset = get_dataset(con, workspace_id, dataset_id)
    tq = safe_table_name(dataset["table_name"])
    row = con.execute(
        "SELECT mode FROM ingest_batches WHERE batch_id = ? AND dataset_id = ? AND workspace_id = ?",
        [batch_id, dataset_id, workspace_id],
    ).fetchone()
    if row is None:
        raise ValueError("batch not found")

    _ensure_batch_column(con, tq)
    deleted = con.execute(f"SELECT count(*) FROM {tq} WHERE {BC} = ?", [batch_id]).fetchone()[0]
    con.execute(f"DELETE FROM {tq} WHERE {BC} = ?", [batch_id])

    restored = 0
    archived = con.execute(
        "SELECT row_json FROM row_archive WHERE batch_id = ? AND workspace_id = ?", [batch_id, workspace_id]
    ).fetchall()
    if archived:
        cols = [c.name for c in get_columns(con, workspace_id, dataset_id)]
        restore_batch = new_id("batch")
        for (rj,) in archived:
            obj = json.loads(rj)
            names = [c for c in cols if c in obj]
            if not names:
                continue
            insert_cols = ", ".join(quote_identifier(c) for c in names) + f", {BC}"
            placeholders = ", ".join("?" for _ in names)
            con.execute(f"INSERT INTO {tq} ({insert_cols}) VALUES ({placeholders}, ?)",
                        [obj[c] for c in names] + [restore_batch])
            restored += 1
        con.execute("DELETE FROM row_archive WHERE batch_id = ? AND workspace_id = ?", [batch_id, workspace_id])

    con.execute("DELETE FROM ingest_batches WHERE batch_id = ? AND dataset_id = ? AND workspace_id = ?",
                [batch_id, dataset_id, workspace_id])
    after = con.execute(f"SELECT count(*) FROM {tq}").fetchone()[0]
    con.execute("UPDATE datasets SET row_count = ? WHERE dataset_id = ? AND workspace_id = ?",
                [after, dataset_id, workspace_id])
    return {"rolled_back": batch_id, "rows_deleted": deleted, "rows_restored": restored, "row_count": after}
