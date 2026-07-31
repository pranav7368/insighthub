"""Data-quality profiling + one-click cleaning.

Reports per-column missing values, whole-row duplicates, numeric outliers
(IQR fences) and mixed-format text columns, then proposes concrete cleaning
actions. Everything is workspace-scoped and every identifier goes through
the same `safe_identifier` whitelist as the rest of the engine, so a
malicious column name can never reach SQL.
"""

from ..core.sqlsafe import safe_identifier, safe_table_name
from .engine import DatasetNotFound, get_columns, get_dataset
from .rls import secured_relation


class QualityError(Exception):
    pass


def compute_quality(con, workspace_id: str, dataset_id: str, user_id: str | None = None) -> dict:
    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DatasetNotFound(f"{dataset_id} is not a structured dataset")
    columns = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in columns}
    # the report describes the rows this member can actually see
    table, rp = secured_relation(con, workspace_id, user_id, dataset)

    row_count = con.execute(f"SELECT count(*) FROM {table}", list(rp)).fetchone()[0]
    distinct_rows = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT * FROM {table})", list(rp)).fetchone()[0]
    duplicate_rows = row_count - distinct_rows

    col_reports, total_missing = [], 0
    for c in columns:
        col = safe_identifier(c.name, allowed)
        non_null = con.execute(f"SELECT count({col}) FROM {table}", list(rp)).fetchone()[0]
        missing = row_count - non_null
        total_missing += missing
        rep = {
            "name": c.name, "role": c.role, "subtype": c.subtype, "distinct_count": c.distinct_count,
            "missing_count": missing, "missing_pct": round(missing / row_count * 100, 1) if row_count else 0.0,
        }
        if c.role == "measure":
            q = con.execute(
                f"SELECT quantile_cont({col},0.25), quantile_cont({col},0.75) FROM {table} WHERE {col} IS NOT NULL",
                list(rp),
            ).fetchone()
            if q and q[0] is not None:
                q1, q3 = q
                iqr = q3 - q1
                if iqr > 0:
                    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                    rep["outlier_count"] = con.execute(
                        f"SELECT count(*) FROM {table} WHERE {col} < ? OR {col} > ?",
                        list(rp) + [lo, hi],
                    ).fetchone()[0]
        elif c.role in ("dimension", "ignored"):
            frac = con.execute(
                f"SELECT avg(CASE WHEN TRY_CAST({col} AS DOUBLE) IS NOT NULL THEN 1.0 ELSE 0.0 END) "
                f"FROM {table} WHERE {col} IS NOT NULL",
                list(rp),
            ).fetchone()[0]
            if frac is not None and 0.1 <= frac <= 0.9:
                rep["mixed_format"] = True
        col_reports.append(rep)

    completeness = round((1 - total_missing / (row_count * len(columns))) * 100, 1) if row_count and columns else 100.0

    suggestions = []
    if duplicate_rows > 0:
        suggestions.append({
            "id": "drop_duplicates", "scope": "dataset", "issue": "duplicate_rows",
            "detail": f"{duplicate_rows} fully-duplicated row(s) found.",
            "actions": ["drop_duplicates"], "severity": "warning",
        })
    for rep in col_reports:
        if rep["missing_count"] > 0:
            numeric = rep["role"] == "measure"
            suggestions.append({
                "id": f"fill_{rep['name']}", "scope": "column", "column": rep["name"], "issue": "missing",
                "detail": f"{rep['missing_pct']}% missing in {rep['name']} ({rep['missing_count']} rows).",
                "actions": ["fill_median", "fill_mean"] if numeric else ["fill_mode"],
                "severity": "warning" if rep["missing_pct"] >= 5 else "info",
            })
        if rep.get("mixed_format"):
            suggestions.append({
                "id": f"format_{rep['name']}", "scope": "column", "column": rep["name"], "issue": "mixed_format",
                "detail": f"{rep['name']} mixes numbers and text — values may not compare correctly.",
                "actions": [], "severity": "info",
            })
        if rep.get("outlier_count"):
            suggestions.append({
                "id": f"outliers_{rep['name']}", "scope": "column", "column": rep["name"], "issue": "outliers",
                "detail": f"{rep['outlier_count']} outlier value(s) in {rep['name']} (beyond 1.5×IQR).",
                "actions": [], "severity": "info",
            })

    return {
        "dataset": dataset, "row_count": row_count, "duplicate_rows": duplicate_rows,
        "completeness_pct": completeness, "columns": col_reports, "suggestions": suggestions,
    }


def apply_cleaning(con, workspace_id: str, dataset_id: str, action: str, column: str | None = None) -> dict:
    dataset = get_dataset(con, workspace_id, dataset_id)
    columns = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in columns}
    table = safe_table_name(dataset["table_name"])

    if action == "drop_duplicates":
        before = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT DISTINCT * FROM {table}")
        after = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        con.execute("UPDATE datasets SET row_count = ? WHERE dataset_id = ? AND workspace_id = ?",
                    [after, dataset_id, workspace_id])
        return {"action": action, "removed": before - after, "row_count": after}

    if action in ("fill_mean", "fill_median", "fill_mode"):
        if column not in allowed:
            raise QualityError("unknown column")
        col = safe_identifier(column, allowed)
        if action == "fill_mean":
            val = con.execute(f"SELECT avg({col}) FROM {table}").fetchone()[0]
        elif action == "fill_median":
            val = con.execute(f"SELECT median({col}) FROM {table}").fetchone()[0]
        else:
            row = con.execute(
                f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY count(*) DESC LIMIT 1"
            ).fetchone()
            val = row[0] if row else None
        if val is None:
            raise QualityError("no value available to fill with")
        filled = con.execute(f"SELECT count(*) FROM {table} WHERE {col} IS NULL").fetchone()[0]
        con.execute(f"UPDATE {table} SET {col} = ? WHERE {col} IS NULL", [val])
        return {"action": action, "column": column, "fill_value": val, "filled": filled}

    raise QualityError(f"unknown cleaning action {action!r}")
