"""Dashboard aggregation engine - pure SQL KPIs, trends, breakdowns.

Two guarantees hold throughout:
  * TENANT ISOLATION - every dataset is loaded WHERE workspace_id = ?; a
    caller can only ever reach datasets in their own workspace.
  * NO INJECTION - every column/table identifier is run through
    `safe_identifier` / `safe_table_name` (validated + whitelisted against
    this dataset's known columns + quoted) before it enters a SQL string;
    every filter VALUE is a bound parameter. No f-string ever carries
    untrusted text into SQL.

No LLM is involved here; every number is a SUM/AVG/COUNT over real rows.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from ..core.sqlsafe import quote_identifier, safe_identifier, safe_table_name
from .correlation import correlation_matrix, scatter_points
from .intelligence import (
    build_insights, detect_anomalies, forecast_series, growth_rates,
    moving_average, pareto_analysis,
)


@dataclass
class ColumnMeta:
    name: str
    role: str
    subtype: str | None
    distinct_count: int


class DatasetNotFound(Exception):
    pass


def get_dataset(con, workspace_id: str, dataset_id: str) -> dict:
    row = con.execute(
        """SELECT dataset_id, name, table_name, kind FROM datasets
           WHERE dataset_id = ? AND workspace_id = ?""",
        [dataset_id, workspace_id],
    ).fetchone()
    if row is None:
        raise DatasetNotFound(dataset_id)
    return {"dataset_id": row[0], "name": row[1], "table_name": row[2], "kind": row[3]}


def _build_treemap(con, table, allowed, dimensions, chosen, where_sql, params):
    """Two-level hierarchy (coarser dimension -> finer) sized by the chosen
    measure. Parent = the dimension with fewer distinct values."""
    if len(dimensions) < 2 or not chosen:
        return None
    dims_sorted = sorted(dimensions, key=lambda d: d.distinct_count)
    parent, child = dims_sorted[0].name, dims_sorted[1].name
    pq = safe_identifier(parent, allowed)
    cq = safe_identifier(child, allowed)
    mq = safe_identifier(chosen, allowed)
    extra = f"{pq} IS NOT NULL AND {cq} IS NOT NULL"
    w = f"{where_sql} AND {extra}" if where_sql else f"WHERE {extra}"
    rows = con.execute(
        f"SELECT {pq} AS p, {cq} AS c, SUM({mq}) AS v FROM {table} {w} "
        f"GROUP BY 1, 2 ORDER BY v DESC NULLS LAST", params
    ).fetchall()
    groups, order = {}, []
    for p, c, v in rows:
        key = str(p)
        if key not in groups:
            groups[key] = []
            order.append(key)
        if len(groups[key]) < 12:
            groups[key].append({"name": str(c), "value": v})
    totals = {p: sum(ch["value"] or 0 for ch in groups[p]) for p in order}
    top_parents = sorted(order, key=lambda p: -totals[p])[:8]
    root = [{"name": p, "value": totals[p], "children": groups[p]} for p in top_parents]
    return {"measure": chosen, "parent_dim": parent, "child_dim": child, "root": root}


def _date_bounds(date_from: str | None, date_to: str | None):
    """Normalize 'YYYY-MM' or 'YYYY-MM-DD' bounds into full timestamps DuckDB
    can cast. The upper bound is exclusive (start of the next month/day) so a
    'to' of 2025-12 correctly includes all of December."""
    def start(s):
        parts = s.split("-")
        return f"{s}-01 00:00:00" if len(parts) == 2 else f"{s} 00:00:00"

    def end_exclusive(s):
        parts = [int(p) for p in s.split("-")]
        if len(parts) == 2:
            y, m = parts
            y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
            return f"{y2:04d}-{m2:02d}-01 00:00:00"
        nxt = date(parts[0], parts[1], parts[2]) + timedelta(days=1)
        return f"{nxt.isoformat()} 00:00:00"

    return (start(date_from) if date_from else None,
            end_exclusive(date_to) if date_to else None)


def get_columns(con, workspace_id: str, dataset_id: str) -> list[ColumnMeta]:
    rows = con.execute(
        """SELECT column_name, role, subtype, distinct_count FROM dataset_columns
           WHERE dataset_id = ? AND workspace_id = ?""",
        [dataset_id, workspace_id],
    ).fetchall()
    return [ColumnMeta(*r) for r in rows]


def compute_dashboard(
    con, workspace_id: str, dataset_id: str,
    filters: dict[str, str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    breakdown_measure: str | None = None,
    user_id: str | None = None,
) -> dict:
    """`user_id` is the member the numbers are computed *for*: their row-level
    rules narrow every query below. None means unrestricted — correct for
    system callers, so endpoints must always pass the authenticated user."""
    # local import: rls imports get_dataset/get_columns from this module
    from .rls import secured_relation

    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DatasetNotFound(f"{dataset_id} is not a structured dataset")

    columns = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in columns}                    # the injection whitelist
    table, rls_params = secured_relation(con, workspace_id, user_id, dataset)

    measures = [c for c in columns if c.role == "measure"]
    dimensions = [c for c in columns if c.role == "dimension"]
    date_cols = [c for c in columns if c.role == "date"]
    date_col = date_cols[0].name if date_cols else None

    from_ts, to_ts = _date_bounds(date_from, date_to)

    def build_where(extra_sql: str | None = None):
        # The row-level filter lives in the relation subquery, which precedes
        # any outer WHERE in the SQL text — so its params bind first. Seeding
        # them here means every query built from build_where is restricted;
        # there is no per-query step to forget.
        clauses, params = [], list(rls_params)
        for column, value in (filters or {}).items():
            clauses.append(f"{safe_identifier(column, allowed)} = ?")
            params.append(value)
        if date_col and from_ts:
            clauses.append(f"TRY_CAST({safe_identifier(date_col, allowed)} AS TIMESTAMP) >= ?")
            params.append(from_ts)
        if date_col and to_ts:
            clauses.append(f"TRY_CAST({safe_identifier(date_col, allowed)} AS TIMESTAMP) < ?")
            params.append(to_ts)
        if extra_sql:
            clauses.append(extra_sql)
        return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params

    where_sql, params = build_where()
    measure_meta = {m.name: m.subtype for m in measures}

    # ---- Trend: all measures grouped by month (drives sparklines, deltas,
    #      forecasts and anomalies too) ----
    trend = []
    series_by_measure: dict[str, list[dict]] = {m.name: [] for m in measures}
    if date_col and measures:
        dcol = safe_identifier(date_col, allowed)
        select_parts = [f"SUM({safe_identifier(m.name, allowed)}) AS {quote_identifier(m.name)}" for m in measures]
        twhere, tparams = build_where(f"TRY_CAST({dcol} AS TIMESTAMP) IS NOT NULL")
        sql = f"""
            SELECT strftime(date_trunc('month', TRY_CAST({dcol} AS TIMESTAMP)), '%Y-%m') AS period,
                   {", ".join(select_parts)}
            FROM {table} {twhere}
            GROUP BY 1 ORDER BY 1
        """
        rows = con.execute(sql, tparams).fetchall()
        cols = [d[0] for d in con.description]
        trend = [dict(zip(cols, r)) for r in rows]
        for m in measures:
            series_by_measure[m.name] = [
                {"period": r["period"], "value": float(r[m.name] or 0)} for r in trend
            ]

    # ---- KPIs: totals + averages + period-over-period delta + sparkline ----
    kpis = []
    if measures:
        parts = []
        for m in measures:
            col = safe_identifier(m.name, allowed)
            parts.append(f'SUM({col}) AS {quote_identifier(m.name + "_total")}')
            parts.append(f'AVG({col}) AS {quote_identifier(m.name + "_avg")}')
        sql = f'SELECT {", ".join(parts)}, COUNT(*) AS row_count FROM {table} {where_sql}'
        row = con.execute(sql, params).fetchone()
        names = [d[0] for d in con.description]
        rec = dict(zip(names, row))
        for m in measures:
            series = series_by_measure.get(m.name, [])
            spark = [p["value"] for p in series][-12:]
            current = series[-1]["value"] if series else None
            previous = series[-2]["value"] if len(series) >= 2 else None
            delta_pct = None
            if current is not None and previous not in (None, 0):
                delta_pct = round((current - previous) / abs(previous) * 100, 1)
            kpis.append({
                "column": m.name, "subtype": m.subtype,
                "total": rec.get(f"{m.name}_total"), "average": rec.get(f"{m.name}_avg"),
                "current_period": current, "previous_period": previous,
                "delta_pct": delta_pct,
                "period_label": series[-1]["period"] if series else None,
                "sparkline": spark,
            })
        row_count = rec.get("row_count", 0)
    else:
        row_count = con.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0]

    # ---- Breakdowns: each dimension x the chosen measure, with share % ----
    breakdowns = {}
    chosen = breakdown_measure if (breakdown_measure in allowed) else (measures[0].name if measures else None)
    if chosen:
        mcol = safe_identifier(chosen, allowed)
        for dim in dimensions:
            dcol = safe_identifier(dim.name, allowed)
            dwhere, dparams = build_where(f"{dcol} IS NOT NULL")
            sql = f"""
                SELECT {dcol} AS name, SUM({mcol}) AS value
                FROM {table} {dwhere}
                GROUP BY 1 ORDER BY value DESC NULLS LAST LIMIT 20
            """
            rows = con.execute(sql, dparams).fetchall()
            total = sum((r[1] or 0) for r in rows) or 1
            breakdowns[dim.name] = {
                "subtype": dim.subtype, "measure": chosen,
                "data": [{"name": r[0], "value": r[1],
                          "share_pct": round((r[1] or 0) / total * 100, 1)} for r in rows],
            }

    # ---- Distributions: five-number summary per measure ----
    distributions = {}
    for m in measures:
        col = safe_identifier(m.name, allowed)
        dwhere, dparams = build_where(f"{col} IS NOT NULL")
        sql = f"""SELECT min({col}), quantile_cont({col},0.25), median({col}),
                         quantile_cont({col},0.75), max({col}), avg({col}), stddev_samp({col})
                  FROM {table} {dwhere}"""
        r = con.execute(sql, dparams).fetchone()
        if r and r[0] is not None:
            distributions[m.name] = {
                "subtype": m.subtype, "min": r[0], "q1": r[1], "median": r[2],
                "q3": r[3], "max": r[4], "mean": r[5], "std": r[6],
            }

    # ---- Filter options ----
    filter_options = {}
    for dim in dimensions:
        dcol = safe_identifier(dim.name, allowed)
        # the only query here not built from build_where — bind the RLS params
        # explicitly, or a restricted user would see every value in the filter
        rows = con.execute(
            f"SELECT DISTINCT {dcol} FROM {table} WHERE {dcol} IS NOT NULL ORDER BY 1 LIMIT 200",
            list(rls_params),
        ).fetchall()
        filter_options[dim.name] = {"subtype": dim.subtype, "values": [r[0] for r in rows]}

    # ---- Data profile: rows, date span, completeness ----
    used_cols = [c for c in columns if c.role in ("measure", "dimension", "date")]
    completeness = None
    if used_cols and row_count:
        count_parts = [f"COUNT({safe_identifier(c.name, allowed)})" for c in used_cols]
        prof = con.execute(f"SELECT {', '.join(count_parts)} FROM {table} {where_sql}", params).fetchone()
        completeness = round(sum(prof) / (row_count * len(used_cols)) * 100, 1)
    date_span = None
    if date_col:
        dcol = safe_identifier(date_col, allowed)
        dr = con.execute(
            f"SELECT min(TRY_CAST({dcol} AS TIMESTAMP)), max(TRY_CAST({dcol} AS TIMESTAMP)) FROM {table} {where_sql}",
            params,
        ).fetchone()
        if dr and dr[0] is not None:
            date_span = {"from": str(dr[0])[:10], "to": str(dr[1])[:10]}
    data_profile = {"rows": row_count, "columns_used": len(used_cols),
                    "completeness_pct": completeness, "date_span": date_span}

    # ---- Intelligence layer: forecasts, anomalies, insights ----
    forecasts, anomalies = {}, {}
    for m in measures:
        series = series_by_measure.get(m.name, [])
        if len(series) >= 4:
            periods = [p["period"] for p in series]
            values = [p["value"] for p in series]
            forecasts[m.name] = forecast_series(periods, values, m.subtype).as_dict()
            forecasts[m.name]["moving_avg"] = moving_average(values)
            found = detect_anomalies(periods, values)
            if found:
                anomalies[m.name] = found

    # ---- Correlations (matrix heatmap) + scatter for the strongest pair ----
    measure_names = [m.name for m in measures]
    correlations = correlation_matrix(con, table, measure_names, allowed, where_sql, params)
    scatter = None
    if correlations and correlations.get("strongest"):
        s = correlations["strongest"]
        scatter = scatter_points(con, table, s["x"], s["y"], allowed, where_sql, params,
                                 measure_meta.get(s["x"]), measure_meta.get(s["y"]))

    # ---- Treemap: two-level category hierarchy sized by the chosen measure ----
    treemap = _build_treemap(con, table, allowed, dimensions, chosen, where_sql, params)

    # ---- Growth rates (MoM/QoQ/YoY) per measure ----
    growth = {m.name: growth_rates(series_by_measure[m.name])
              for m in measures if series_by_measure.get(m.name)}

    # ---- Pareto (80/20) on the primary breakdown dimension ----
    pareto = None
    if breakdowns and chosen:
        first_dim = next(iter(breakdowns))
        pareto = pareto_analysis(breakdowns[first_dim]["data"])
        if pareto:
            pareto.update({"dimension": first_dim, "measure": chosen})

    insights = [
        i.as_dict() for i in build_insights(
            measures=[{"name": m.name, "subtype": m.subtype} for m in measures],
            series_by_measure=series_by_measure,
            breakdowns=breakdowns,
            forecasts=forecasts,
            anomalies=anomalies,
            primary_measure=chosen,
            pareto=pareto,
        )
    ]

    return {
        "dataset": dataset,
        "row_count_filtered": row_count,
        "kpis": kpis,
        "trend": trend,
        "measures": [{"name": m.name, "subtype": m.subtype} for m in measures],
        "breakdowns": breakdowns,
        "distributions": distributions,
        "correlations": correlations,
        "scatter": scatter,
        "treemap": treemap,
        "growth": growth,
        "pareto": pareto,
        "forecasts": forecasts,
        "anomalies": anomalies,
        "insights": insights,
        "data_profile": data_profile,
        "filter_options": filter_options,
        "date_column": date_col,
        "chosen_measure": chosen,
    }
