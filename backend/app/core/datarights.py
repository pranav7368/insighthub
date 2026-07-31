"""Data subject rights: export and erasure.

DPDP's full-compliance deadline is 13 May 2027 and GDPR has required the same
primitives since 2018. Both need the ability to (a) produce everything held
about a person and (b) delete it. Building them once satisfies both.

Two distinct subjects exist here, and conflating them is how products get this
wrong:

* a **member** — someone with a login. Their personal data is the account row
  and the trail of what they did.
* a **workspace** — the customer. Erasing it removes the uploaded data itself,
  including the physical per-dataset tables, which is what
  "deletion on termination" in a processor agreement actually means.

Design decisions worth keeping:

* **The table list is derived, not hand-written.** Every table carrying a
  `workspace_id` is discovered from the live catalog, so a table added later is
  covered by erasure automatically. A hand-maintained list would silently rot
  and leave data behind — the exact failure that turns a deletion request into
  a breach notification.
* **Erasure is verified.** `erase_workspace` re-counts afterwards and raises if
  anything survived, rather than reporting success it did not achieve.
* **Audit entries survive member erasure, de-identified.** Security logs are
  legitimate-interest data and deleting them wholesale destroys the evidence
  trail; the user_id is overwritten instead so the row no longer identifies
  anyone.
"""

import json
from datetime import datetime, timezone

from .sqlsafe import safe_table_name

# Tables that hold a workspace's own content. Discovered at runtime, but this
# is the fallback when the catalog is unavailable (e.g. a mocked connection).
_KNOWN_WORKSPACE_TABLES = (
    "datasets", "dataset_columns", "chunks", "chunk_embeddings", "audit_log",
    "ingest_batches", "row_archive", "data_sources", "dashboard_views",
    "share_links", "alerts", "metrics", "subscriptions", "dataset_relations",
    "rls_rules", "column_policies", "users",
)


class DataRightsError(Exception):
    """An export or erasure could not be completed."""


def _tables_with_workspace_id(con) -> list[str]:
    """Every table carrying a workspace_id, from the live catalog.

    Derived rather than listed so a table added next year is erased too.
    """
    try:
        rows = con.execute(
            """SELECT DISTINCT table_name FROM information_schema.columns
               WHERE column_name = 'workspace_id'"""
        ).fetchall()
        found = sorted(r[0] for r in rows)
        if found:
            return found
    except Exception:
        pass
    return list(_KNOWN_WORKSPACE_TABLES)


def _rows_as_dicts(con, sql: str, params: list) -> list[dict]:
    cursor = con.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ------------------------------------------------------------- export -----

def export_member(con, workspace_id: str, user_id: str) -> dict:
    """Everything held about one member, in a portable form.

    GDPR Art. 20 wants "structured, commonly used, machine-readable"; JSON is
    both, and it is what an engineer receiving the request can actually check.
    """
    account = _rows_as_dicts(
        con,
        """SELECT user_id, workspace_id, email, role, created_at
           FROM users WHERE user_id = ? AND workspace_id = ?""",
        [user_id, workspace_id],
    )
    if not account:
        raise DataRightsError("no such member in this workspace")

    return {
        "subject": "member",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account": account[0],
        # what they did — their personal activity trail
        "activity": _rows_as_dicts(
            con,
            """SELECT ts, action, detail FROM audit_log
               WHERE workspace_id = ? AND user_id = ? ORDER BY ts""",
            [workspace_id, user_id],
        ),
        # content attributable to them
        "share_links_created": _rows_as_dicts(
            con,
            """SELECT token, dataset_id, label, created_at, revoked FROM share_links
               WHERE workspace_id = ? AND created_by = ?""",
            [workspace_id, user_id],
        ),
        "alerts_created": _rows_as_dicts(
            con,
            """SELECT alert_id, name, measure, webhook_url, created_at FROM alerts
               WHERE workspace_id = ? AND created_by = ?""",
            [workspace_id, user_id],
        ),
        "row_access_rules": _rows_as_dicts(
            con,
            """SELECT rule_id, dataset_id, column_name, operator, allowed_values
               FROM rls_rules WHERE workspace_id = ? AND user_id = ?""",
            [workspace_id, user_id],
        ),
        "note": (
            "Datasets uploaded to this workspace belong to the workspace, not to an "
            "individual member, and are covered by the workspace export."
        ),
    }


def export_workspace(con, workspace_id: str) -> dict:
    """Everything the workspace holds, table by table. The processor-side
    answer to 'give us our data back'."""
    export: dict = {
        "subject": "workspace",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace_id": workspace_id,
        "tables": {},
    }
    for table in _tables_with_workspace_id(con):
        if table == "users":
            rows = _rows_as_dicts(
                con,
                "SELECT user_id, email, role, created_at FROM users WHERE workspace_id = ?",
                [workspace_id],
            )   # never export password hashes
        else:
            rows = _rows_as_dicts(con, f"SELECT * FROM {table} WHERE workspace_id = ?",
                                  [workspace_id])
        if rows:
            export["tables"][table] = rows
    return export


# ------------------------------------------------------------ erasure -----

def erase_member(con, workspace_id: str, user_id: str) -> dict:
    """Erase a member. Their audit trail is de-identified rather than deleted.

    Wiping the security log with the account destroys the record of what
    happened, which is neither required by either regime nor wise; overwriting
    the identifier satisfies erasure while keeping the evidence.
    """
    exists = con.execute(
        "SELECT count(*) FROM users WHERE user_id = ? AND workspace_id = ?",
        [user_id, workspace_id],
    ).fetchone()[0]
    if not exists:
        raise DataRightsError("no such member in this workspace")

    con.execute("DELETE FROM rls_rules WHERE workspace_id = ? AND user_id = ?",
                [workspace_id, user_id])
    con.execute("UPDATE share_links SET created_by = NULL WHERE workspace_id = ? AND created_by = ?",
                [workspace_id, user_id])
    con.execute("UPDATE alerts SET created_by = NULL WHERE workspace_id = ? AND created_by = ?",
                [workspace_id, user_id])
    con.execute("UPDATE audit_log SET user_id = 'erased' WHERE workspace_id = ? AND user_id = ?",
                [workspace_id, user_id])
    con.execute("DELETE FROM users WHERE user_id = ? AND workspace_id = ?", [user_id, workspace_id])

    return {"erased": "member", "user_id": user_id, "audit_retained_deidentified": True}


def erase_workspace(con, workspace_id: str) -> dict:
    """Erase a workspace and every trace of its data, including the physical
    per-dataset tables — deletion-on-termination, done properly.

    Verifies afterwards and raises if anything survived. Reporting a deletion
    that did not happen is worse than failing loudly.
    """
    dropped = []
    for (table_name,) in con.execute(
        "SELECT table_name FROM datasets WHERE workspace_id = ? AND table_name IS NOT NULL",
        [workspace_id],
    ).fetchall():
        try:
            con.execute(f"DROP TABLE IF EXISTS {safe_table_name(table_name)}")
            dropped.append(table_name)
        except Exception as exc:            # noqa: BLE001 — recorded, not swallowed
            raise DataRightsError(f"could not drop raw table {table_name}: {exc}")

    tables = _tables_with_workspace_id(con)
    deleted: dict[str, int] = {}
    for table in tables:
        before = con.execute(f"SELECT count(*) FROM {table} WHERE workspace_id = ?",
                             [workspace_id]).fetchone()[0]
        if before:
            con.execute(f"DELETE FROM {table} WHERE workspace_id = ?", [workspace_id])
            deleted[table] = before
    con.execute("DELETE FROM workspaces WHERE workspace_id = ?", [workspace_id])

    # verify — never claim an erasure we did not achieve
    survivors = {
        table: con.execute(f"SELECT count(*) FROM {table} WHERE workspace_id = ?",
                           [workspace_id]).fetchone()[0]
        for table in tables
    }
    remaining = {t: n for t, n in survivors.items() if n}
    if remaining:
        raise DataRightsError(f"erasure incomplete, rows remain in: {remaining}")

    return {"erased": "workspace", "workspace_id": workspace_id,
            "raw_tables_dropped": dropped, "rows_deleted": deleted}


def as_download(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)
