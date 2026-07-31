"""Correlation analysis + scatter data.

`correlation_matrix` and `scatter_points` are pure helpers (they take an
already-validated table + column whitelist), so the dashboard engine can
call them without an import cycle. `compute_scatter` is the standalone entry
for an arbitrary (x, y) pair behind the /scatter endpoint; it lazily imports
the engine to resolve the dataset and reuse the same filter semantics.

All numbers are computed from the real rows (numpy/pandas) - nothing here is
an LLM guess. Identifiers pass through `safe_identifier`; filter values are
bound parameters.
"""

import numpy as np
import pandas as pd

from ..core.sqlsafe import safe_identifier, safe_table_name


def correlation_matrix(con, table_quoted, measure_names, allowed, where_sql, params):
    """Pairwise Pearson correlation across the numeric measures."""
    if len(measure_names) < 2:
        return None
    cols = ", ".join(safe_identifier(m, allowed) for m in measure_names)
    df = con.execute(f"SELECT {cols} FROM {table_quoted} {where_sql}", params).df()
    if df.shape[0] < 3:
        return None
    corr = df.corr(numeric_only=True)
    measures = [str(c) for c in corr.columns]
    matrix = [
        [None if pd.isna(corr.iloc[i, j]) else round(float(corr.iloc[i, j]), 2)
         for j in range(len(measures))]
        for i in range(len(measures))
    ]
    strongest, best = None, -1.0
    for i in range(len(measures)):
        for j in range(i + 1, len(measures)):
            v = corr.iloc[i, j]
            if pd.notna(v) and abs(v) > best:
                best = abs(v)
                strongest = {"x": measures[i], "y": measures[j], "r": round(float(v), 2)}
    return {"measures": measures, "matrix": matrix, "strongest": strongest}


def scatter_points(con, table_quoted, x, y, allowed, where_sql, params,
                   subtype_x=None, subtype_y=None, max_points=400):
    """Raw (x, y) points for two measures + correlation r + regression line.
    Points are systematically down-sampled past max_points to keep payloads
    small without biasing the shape."""
    xq, yq = safe_identifier(x, allowed), safe_identifier(y, allowed)
    extra = f"{xq} IS NOT NULL AND {yq} IS NOT NULL"
    w = f"{where_sql} AND {extra}" if where_sql else f"WHERE {extra}"
    rows = con.execute(f"SELECT {xq}, {yq} FROM {table_quoted} {w}", params).fetchall()
    if len(rows) > max_points:
        step = len(rows) / max_points
        rows = [rows[int(i * step)] for i in range(max_points)]

    xs = np.array([float(r[0]) for r in rows]) if rows else np.array([])
    ys = np.array([float(r[1]) for r in rows]) if rows else np.array([])
    r = line = None
    if len(xs) >= 3 and xs.std() > 0 and ys.std() > 0:
        r = float(np.corrcoef(xs, ys)[0, 1])
        slope, intercept = (float(v) for v in np.polyfit(xs, ys, 1))
        xmin, xmax = float(xs.min()), float(xs.max())
        line = [{"x": xmin, "y": slope * xmin + intercept},
                {"x": xmax, "y": slope * xmax + intercept}]
    return {
        "x": x, "y": y, "subtype_x": subtype_x, "subtype_y": subtype_y,
        "points": [{"x": float(a), "y": float(b)} for a, b in rows],
        "r": round(r, 3) if r is not None else None, "line": line,
    }


def compute_scatter(con, workspace_id, dataset_id, x, y,
                    filters=None, date_from=None, date_to=None):
    from .engine import DatasetNotFound, _date_bounds, get_columns, get_dataset

    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DatasetNotFound(f"{dataset_id} is not a structured dataset")
    columns = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in columns}
    measures = {c.name: c.subtype for c in columns if c.role == "measure"}
    if x not in measures or y not in measures:
        raise ValueError("x and y must both be numeric measures")

    table = safe_table_name(dataset["table_name"])
    date_col = next((c.name for c in columns if c.role == "date"), None)
    from_ts, to_ts = _date_bounds(date_from, date_to)
    clauses, params = [], []
    for col, val in (filters or {}).items():
        if col in allowed:
            clauses.append(f"{safe_identifier(col, allowed)} = ?")
            params.append(val)
    if date_col and from_ts:
        clauses.append(f"TRY_CAST({safe_identifier(date_col, allowed)} AS TIMESTAMP) >= ?")
        params.append(from_ts)
    if date_col and to_ts:
        clauses.append(f"TRY_CAST({safe_identifier(date_col, allowed)} AS TIMESTAMP) < ?")
        params.append(to_ts)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return scatter_points(con, table, x, y, allowed, where_sql, params, measures[x], measures[y])
