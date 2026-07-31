"""Multi-table joins — link two datasets on a key and analyse the result.

The join is **materialized** into a new structured dataset: every existing
analytic (dashboard, metrics, drivers, ask) works on it unchanged because it is
just another dataset. The relation is recorded so the joined dataset can be
rebuilt from fresh source data.

Security: the join SQL is built only from identifiers whitelisted to each
dataset's real columns (`safe_identifier`) and system-generated, quoted table
names — never free-form input.
"""

from ..core import db
from ..core.security import new_id
from ..core.sqlsafe import quote_identifier, safe_identifier, safe_table_name, sanitize_identifier
from ..ingest.pipeline import _dedupe_columns, create_structured_dataset
from .detect import detect_schema
from .engine import get_columns, get_dataset

JOIN_TYPES = ("inner", "left")


class JoinError(ValueError):
    """A join could not be created (bad key, no match, non-structured, …)."""


class RelationNotFound(JoinError):
    """No such relation in this workspace."""


def _id_like(cols: list[str]) -> str | None:
    for c in cols:
        if c.lower().endswith("_id") or c.lower() == "id":
            return c
    return cols[0] if cols else None


def suggest_join_keys(con, workspace_id: str, left_id: str, right_id: str) -> dict:
    left_cols = [c.name for c in get_columns(con, workspace_id, left_id)]   # DatasetNotFound → 404
    right_cols = [c.name for c in get_columns(con, workspace_id, right_id)]
    common = [c for c in left_cols if c in set(right_cols)]
    key = _id_like(common) if common else None
    return {
        "left_columns": left_cols,
        "right_columns": right_cols,
        "common": common,
        "suggested": ({"left_key": key, "right_key": key} if key else None),
    }


def _build_join_df(con, workspace_id, left_id, right_id, left_key, right_key, join_type):
    left = get_dataset(con, workspace_id, left_id)
    right = get_dataset(con, workspace_id, right_id)
    if left["kind"] != "structured" or right["kind"] != "structured":
        raise JoinError("both sides of a join must be spreadsheet datasets")

    left_cols = [c.name for c in get_columns(con, workspace_id, left_id)]
    right_cols = [c.name for c in get_columns(con, workspace_id, right_id)]
    left_allowed, right_allowed = set(left_cols), set(right_cols)
    if left_key not in left_allowed:
        raise JoinError(f"{left_key!r} is not a column of the left dataset")
    if right_key not in right_allowed:
        raise JoinError(f"{right_key!r} is not a column of the right dataset")

    lq, rq = safe_table_name(left["table_name"]), safe_table_name(right["table_name"])
    rslug = sanitize_identifier(right["name"]) or "right"

    select_parts = [f"L.{safe_identifier(c, left_allowed)} AS {quote_identifier(c)}" for c in left_cols]
    for c in right_cols:
        if c == right_key:
            continue  # duplicates the left key — drop it
        out = c if c not in left_allowed else sanitize_identifier(f"{rslug}_{c}")
        select_parts.append(f"R.{safe_identifier(c, right_allowed)} AS {quote_identifier(out)}")

    jtype = "INNER" if join_type == "inner" else "LEFT"
    sql = (
        f"SELECT {', '.join(select_parts)} FROM {lq} L "
        f"{jtype} JOIN {rq} R "
        f"ON L.{safe_identifier(left_key, left_allowed)} = R.{safe_identifier(right_key, right_allowed)}"
    )
    return con.execute(sql).df()


def create_join(con, workspace_id, left_id, right_id, left_key, right_key,
                join_type="left", name=None) -> dict:
    if join_type not in JOIN_TYPES:
        join_type = "left"
    df = _build_join_df(con, workspace_id, left_id, right_id, left_key, right_key, join_type)
    if df.empty:
        raise JoinError("the join produced no rows — check the join keys")

    left = get_dataset(con, workspace_id, left_id)
    right = get_dataset(con, workspace_id, right_id)
    ds_name = (name or "").strip() or f"{left['name']} + {right['name']}"
    result = create_structured_dataset(con, workspace_id, ds_name, df, source_file="join")

    relation_id = new_id("rel")
    con.execute(
        """INSERT INTO dataset_relations
           (relation_id, workspace_id, dataset_id, left_dataset_id, right_dataset_id,
            left_key, right_key, join_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [relation_id, workspace_id, result.dataset_id, left_id, right_id, left_key, right_key, join_type],
    )
    return {"relation_id": relation_id, "dataset_id": result.dataset_id,
            "name": ds_name, "row_count": result.row_count}


def _get_relation(con, workspace_id, relation_id) -> dict:
    r = con.execute(
        """SELECT relation_id, dataset_id, left_dataset_id, right_dataset_id,
                  left_key, right_key, join_type
           FROM dataset_relations WHERE relation_id = ? AND workspace_id = ?""",
        [relation_id, workspace_id],
    ).fetchone()
    if r is None:
        raise RelationNotFound("join not found")
    keys = ["relation_id", "dataset_id", "left_dataset_id", "right_dataset_id",
            "left_key", "right_key", "join_type"]
    return dict(zip(keys, r))


def list_relations(con, workspace_id) -> list[dict]:
    rows = con.execute(
        """SELECT r.relation_id, r.dataset_id, r.left_dataset_id, r.right_dataset_id,
                  r.left_key, r.right_key, r.join_type, r.created_at, d.name, d.row_count
           FROM dataset_relations r
           JOIN datasets d ON d.dataset_id = r.dataset_id AND d.workspace_id = r.workspace_id
           WHERE r.workspace_id = ? ORDER BY r.created_at DESC""",
        [workspace_id],
    ).fetchall()

    def name_of(dsid):
        row = con.execute("SELECT name FROM datasets WHERE dataset_id = ? AND workspace_id = ?",
                          [dsid, workspace_id]).fetchone()
        return row[0] if row else "(deleted)"

    out = []
    for r in rows:
        out.append({
            "relation_id": r[0], "dataset_id": r[1],
            "left_dataset_id": r[2], "right_dataset_id": r[3],
            "left_key": r[4], "right_key": r[5], "join_type": r[6],
            "created_at": str(r[7]), "name": r[8], "row_count": r[9],
            "left_name": name_of(r[2]), "right_name": name_of(r[3]),
        })
    return out


def rebuild_join(con, workspace_id, relation_id) -> dict:
    """Re-run the join from current source data, refreshing the joined dataset
    in place (same dataset_id, so selections/dashboards don't break)."""
    rel = _get_relation(con, workspace_id, relation_id)
    df = _build_join_df(con, workspace_id, rel["left_dataset_id"], rel["right_dataset_id"],
                        rel["left_key"], rel["right_key"], rel["join_type"])
    if df.empty:
        raise JoinError("the rebuilt join produced no rows — check the source data / keys")

    dataset = get_dataset(con, workspace_id, rel["dataset_id"])
    tq = safe_table_name(dataset["table_name"])
    df.columns = _dedupe_columns([sanitize_identifier(c) for c in df.columns])
    profiles = detect_schema(df)

    con.register("_join_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {tq} AS SELECT * FROM _join_df")
    con.unregister("_join_df")
    con.execute(f"ALTER TABLE {tq} ADD COLUMN {quote_identifier(db.BATCH_COL)} VARCHAR")

    con.execute("DELETE FROM dataset_columns WHERE dataset_id = ? AND workspace_id = ?",
                [rel["dataset_id"], workspace_id])
    con.executemany(
        """INSERT INTO dataset_columns (dataset_id, workspace_id, column_name, role, subtype, distinct_count, overridden)
           VALUES (?, ?, ?, ?, ?, ?, false)""",
        [(rel["dataset_id"], workspace_id, p.name, p.role, p.subtype, p.distinct_count) for p in profiles],
    )
    con.execute("UPDATE datasets SET row_count = ? WHERE dataset_id = ? AND workspace_id = ?",
                [len(df), rel["dataset_id"], workspace_id])
    return {"dataset_id": rel["dataset_id"], "row_count": len(df)}


def delete_relation(con, workspace_id, relation_id) -> int:
    row = con.execute(
        "SELECT dataset_id FROM dataset_relations WHERE relation_id = ? AND workspace_id = ?",
        [relation_id, workspace_id],
    ).fetchone()
    if row is None:
        return 0
    dataset_id = row[0]
    ds = con.execute("SELECT table_name FROM datasets WHERE dataset_id = ? AND workspace_id = ?",
                     [dataset_id, workspace_id]).fetchone()
    if ds and ds[0]:
        con.execute(f"DROP TABLE IF EXISTS {safe_table_name(ds[0])}")
    for table in ("datasets", "dataset_columns", "ingest_batches"):
        con.execute(f"DELETE FROM {table} WHERE dataset_id = ? AND workspace_id = ?",
                    [dataset_id, workspace_id])
    con.execute("DELETE FROM dataset_relations WHERE relation_id = ? AND workspace_id = ?",
                [relation_id, workspace_id])
    return 1
