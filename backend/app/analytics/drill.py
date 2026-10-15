"""Drill-down — every number on the dashboard can be opened and taken apart.

The unit of work is a *slice*: a measure, an aggregation, a set of
`column = value` filters and an optional date range. Three questions are asked
of a slice, each answered with plain SQL:

  * `inspect`   — the number itself, how it is calculated (formula in words +
                  the SQL), its spread, its trend at any time grain, the
                  comparison with the previous period and the same period a
                  year earlier, and its biggest contributors per dimension.
  * `breakdown` — the slice split by one dimension, fully ranked, with the
                  long tail reported as an explicit "other" bucket.
  * `records`   — the actual rows behind the number, paged and sortable.

Drilling deeper is just adding a filter or narrowing the date range, so the
three compose without limit: Revenue -> North -> Delhi -> March -> the rows.

Same guarantees as the engine: identifiers are whitelisted against the
dataset's columns, every value is a bound parameter, and every read goes
through `rls.secured_relation` so row rules and PII masking apply to the rows
a member drills into exactly as they apply to the dashboard.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from ..core.sqlsafe import safe_identifier
from .engine import _date_bounds, get_columns, get_dataset

AGGREGATIONS = ("sum", "avg", "count", "min", "max", "median")
GRAINS = ("day", "week", "month", "quarter", "year")
_AGG_WORDS = {"sum": "Sum", "avg": "Average", "count": "Count of rows", "min": "Minimum",
              "max": "Maximum", "median": "Median"}
# aggregations whose parts add up to the whole — only these have a "share"
_ADDITIVE = ("sum", "count")

MAX_PAGE_SIZE = 200
MAX_BREAKDOWN = 500
TOP_CONTRIBUTORS = 5
MAX_TREND_POINTS = 400


class DrillError(ValueError):
    """The slice could not be built (unknown column, bad aggregation…)."""


@dataclass
class _Slice:
    dataset: dict
    columns: list
    allowed: set
    relation: str
    rls_params: list
    date_col: str | None
    measures: dict          # name -> subtype
    dimensions: dict        # name -> subtype
    filters: dict
    date_from: str | None
    date_to: str | None

    def where(self, extra: str | None = None, *, dates: bool = True) -> tuple[str, list, list]:
        """(WHERE sql, all params, the user's own params). The RLS params lead
        because the secured relation precedes the WHERE in the SQL text."""
        clauses, own = [], []
        for column, value in self.filters.items():
            clauses.append(f"{safe_identifier(column, self.allowed)} = ?")
            own.append(value)
        if dates and self.date_col:
            from_ts, to_ts = _date_bounds(self.date_from, self.date_to)
            dq = safe_identifier(self.date_col, self.allowed)
            if from_ts:
                clauses.append(f"TRY_CAST({dq} AS TIMESTAMP) >= ?")
                own.append(from_ts)
            if to_ts:
                clauses.append(f"TRY_CAST({dq} AS TIMESTAMP) < ?")
                own.append(to_ts)
        if extra:
            clauses.append(extra)
        sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return sql, list(self.rls_params) + own, own


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


def _check_date(s: str) -> None:
    m = _DATE_RE.match(str(s))
    try:
        if not m:
            raise ValueError
        date(int(m[1]), int(m[2]), int(m[3] or 1))
    except ValueError:
        raise DrillError(f"bad date {s!r} (use YYYY-MM or YYYY-MM-DD)")


def _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to, public=False) -> _Slice:
    from .rls import secured_relation

    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DrillError("drill-down only applies to spreadsheet datasets")
    columns = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in columns}
    clean = {}
    for column, value in (filters or {}).items():
        if column not in allowed:
            raise DrillError(f"unknown column {column!r}")
        if value is None or isinstance(value, (dict, list)):
            raise DrillError(f"filter on {column!r} needs a single value")
        clean[column] = str(value)
    for bound in (date_from, date_to):
        if bound is not None:
            _check_date(bound)
    relation, rls_params = secured_relation(con, workspace_id, user_id, dataset, public=public)
    return _Slice(
        dataset=dataset, columns=columns, allowed=allowed,
        relation=relation, rls_params=list(rls_params),
        date_col=next((c.name for c in columns if c.role == "date"), None),
        measures={c.name: c.subtype for c in columns if c.role == "measure"},
        dimensions={c.name: c.subtype for c in columns if c.role == "dimension"},
        filters=clean, date_from=date_from, date_to=date_to,
    )


def _value_expr(sl: _Slice, measure: str | None, agg: str) -> str:
    if agg not in AGGREGATIONS:
        raise DrillError(f"unknown aggregation {agg!r}")
    if agg == "count":
        return "COUNT(*)"
    if not measure:
        raise DrillError("a measure is required for this aggregation")
    if measure not in sl.measures:
        raise DrillError(f"{measure!r} is not a numeric measure")
    return f"{agg.upper()}({safe_identifier(measure, sl.allowed)})"


def _resolve_measure(sl: _Slice, measure: str | None, agg: str) -> str | None:
    if measure:
        return measure
    if agg == "count":
        return None
    if not sl.measures:
        raise DrillError("this dataset has no numeric measure")
    return next(iter(sl.measures))


def _display_sql(sl: _Slice, sql: str, own_params: list) -> str:
    """Readable rendering of a query for the "how it's calculated" view: the
    internal relation becomes the dataset's name and the member's own filter
    values are inlined. Row-rule values stay out — the response says that row
    rules applied, without echoing them. Display only; execution stays bound."""
    name = (sl.dataset["name"] or "dataset").replace('"', "'")
    disp = sql.replace(sl.relation, f'"{name}"', 1)
    for p in own_params:
        lit = "NULL" if p is None else (f"'{p}'" if isinstance(p, str) else str(p))
        disp = disp.replace("?", lit, 1)
    return " ".join(disp.split())


def _period_expr(dq: str, grain: str) -> str:
    ts = f"TRY_CAST({dq} AS TIMESTAMP)"
    if grain == "day":
        return f"strftime(date_trunc('day', {ts}), '%Y-%m-%d')"
    if grain == "week":
        return f"strftime(date_trunc('week', {ts}), '%Y-%m-%d')"
    if grain == "month":
        return f"strftime(date_trunc('month', {ts}), '%Y-%m')"
    if grain == "quarter":
        return f"(strftime({ts}, '%Y') || '-Q' || CAST(quarter({ts}) AS VARCHAR))"
    if grain == "year":
        return f"strftime({ts}, '%Y')"
    raise DrillError(f"unknown grain {grain!r}")


def period_bounds(label: str, grain: str) -> tuple[str, str]:
    """Inclusive (date_from, date_to) covering one period label — the values a
    drill into that period sends back."""
    if grain == "day":
        return label, label
    if grain == "week":
        start = date.fromisoformat(label)
        return label, (start + timedelta(days=6)).isoformat()
    if grain == "month":
        return label, label
    if grain == "quarter":
        year, q = label.split("-Q")
        first = (int(q) - 1) * 3 + 1
        return f"{year}-{first:02d}", f"{year}-{first + 2:02d}"
    if grain == "year":
        return f"{label}-01", f"{label}-12"
    raise DrillError(f"unknown grain {grain!r}")


def year_ago(label: str, grain: str) -> str:
    if grain == "day":
        d = date.fromisoformat(label)
        try:
            return d.replace(year=d.year - 1).isoformat()
        except ValueError:        # 29 Feb -> 28 Feb
            return d.replace(year=d.year - 1, day=28).isoformat()
    if grain == "week":           # 52 weeks back keeps the same weekday
        return (date.fromisoformat(label) - timedelta(days=364)).isoformat()
    year, rest = label[:4], label[4:]
    return f"{int(year) - 1:04d}{rest}"


def _pct(new, old):
    if new is None or old in (None, 0):
        return None
    return (new - old) / abs(old) * 100.0


def _compare(points: list[dict], grain: str) -> dict | None:
    if not points:
        return None
    by_period = {p["period"]: p for p in points}
    last = points[-1]
    out = {"period": last["period"], "value": last["value"], "previous": None, "year_ago": None}
    if len(points) >= 2:
        prev = points[-2]
        out["previous"] = {"period": prev["period"], "value": prev["value"],
                           "delta": (last["value"] or 0) - (prev["value"] or 0),
                           "pct": _pct(last["value"], prev["value"])}
    ya = by_period.get(year_ago(last["period"], grain))
    if ya:
        out["year_ago"] = {"period": ya["period"], "value": ya["value"],
                           "delta": (last["value"] or 0) - (ya["value"] or 0),
                           "pct": _pct(last["value"], ya["value"])}
    return out


def _describe(sl: _Slice, measure: str | None, agg: str, rows: int, skipped: int) -> str:
    what = "Count of rows" if agg == "count" else f"{_AGG_WORDS[agg]} of {measure.replace('_', ' ')}"
    text = f"{what} across {rows:,} row{'s' if rows != 1 else ''}"
    conds = [f"{k.replace('_', ' ')} = {v}" for k, v in sl.filters.items()]
    if sl.date_from and sl.date_to:
        conds.append(f"{sl.date_col.replace('_', ' ')} from {sl.date_from} to {sl.date_to}"
                     if sl.date_from != sl.date_to else
                     f"{sl.date_col.replace('_', ' ')} in {sl.date_from}")
    elif sl.date_from:
        conds.append(f"{sl.date_col.replace('_', ' ')} from {sl.date_from}")
    elif sl.date_to:
        conds.append(f"{sl.date_col.replace('_', ' ')} up to {sl.date_to}")
    if conds:
        text += " where " + " and ".join(conds)
    text += "."
    if skipped:
        text += (f" {skipped:,} row{'s' if skipped != 1 else ''} with no "
                 f"{measure.replace('_', ' ')} value {'are' if skipped != 1 else 'is'} not counted.")
    return text


# ---------------------------------------------------------------- inspect ---

def inspect(con, workspace_id, dataset_id, *, measure=None, agg="sum", filters=None,
            date_from=None, date_to=None, grain="month", user_id=None, public=False) -> dict:
    from .rls import restricts

    sl = _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to, public)
    if grain not in GRAINS:
        raise DrillError(f"unknown grain {grain!r}")
    measure = _resolve_measure(sl, measure, agg)
    vexpr = _value_expr(sl, measure, agg)
    subtype = sl.measures.get(measure) if agg != "count" else None
    rel = sl.relation

    where, params, own = sl.where()
    mq = safe_identifier(measure, sl.allowed) if measure else None
    stats_sql = (f", COUNT({mq}), MIN({mq}), MEDIAN({mq}), AVG({mq}), MAX({mq}), STDDEV_SAMP({mq})"
                 if mq else "")
    headline_sql = f"SELECT {vexpr} AS value FROM {rel} {where}"
    row = con.execute(f"SELECT {vexpr}, COUNT(*){stats_sql} FROM {rel} {where}", params).fetchone()
    value, row_count = row[0], row[1]
    stats, skipped = None, 0
    if mq:
        non_null = row[2]
        skipped = row_count - non_null
        stats = {"rows_with_value": non_null, "min": row[3], "median": row[4],
                 "avg": row[5], "max": row[6], "std": row[7]}

    # ---- trend at the requested grain ----
    trend = None
    if sl.date_col:
        dq = safe_identifier(sl.date_col, sl.allowed)
        pexpr = _period_expr(dq, grain)
        twhere, tparams, _ = sl.where(f"TRY_CAST({dq} AS TIMESTAMP) IS NOT NULL")
        rows = con.execute(
            f"SELECT {pexpr} AS period, {vexpr} AS value, COUNT(*) AS n "
            f"FROM {rel} {twhere} GROUP BY 1 ORDER BY 1", tparams,
        ).fetchall()
        points = []
        for period, v, n in rows[-MAX_TREND_POINTS:]:
            lo, hi = period_bounds(period, grain)
            points.append({"period": period, "value": v, "rows": n, "from": lo, "to": hi})
        comparison = _compare(points, grain)
        # A period that the data stops partway through compares unfairly with a
        # whole one — say so instead of letting a half-month read as a drop.
        # "Where the data stops" is the dataset's last date, not this slice's:
        # a store with no sale after the 21st has a complete month, not half.
        latest_date = con.execute(f"SELECT MAX(TRY_CAST({dq} AS TIMESTAMP)) FROM {rel}",
                                  list(sl.rls_params)).fetchone()[0]
        partial = False
        if points and latest_date is not None and grain != "day":
            _, end_excl = _date_bounds(None, points[-1]["to"])
            partial = str(latest_date)[:10] < (date.fromisoformat(end_excl[:10]) - timedelta(days=1)).isoformat()
        trend = {"grain": grain, "points": points, "truncated": len(rows) > MAX_TREND_POINTS,
                 "comparison": comparison, "latest_period_partial": partial,
                 "data_through": str(latest_date)[:10] if latest_date is not None else None}

    # ---- top contributors per dimension (skip dimensions already pinned) ----
    contributors = _contributors(con, sl, measure, agg, vexpr, TOP_CONTRIBUTORS, value)

    notes = []
    if user_id and restricts(con, workspace_id, user_id, dataset_id):
        notes.append("This link covers only the rows its author can see." if public else
                     "Your row-access rules apply: this number covers only the rows you are allowed to see.")
    if skipped:
        notes.append(f"{skipped:,} row{'s' if skipped != 1 else ''} have no {measure.replace('_', ' ')} "
                     "value and are left out of the calculation.")
    if trend and trend["latest_period_partial"]:
        notes.append(f"The data ends on {trend['data_through']}, partway through "
                     f"{trend['points'][-1]['period']} — that period is incomplete, so compare it with care.")

    return {
        "dataset": {"dataset_id": sl.dataset["dataset_id"], "name": sl.dataset["name"]},
        "measure": measure, "agg": agg, "subtype": subtype,
        "value": value, "row_count": row_count,
        "context": {"filters": sl.filters, "date_from": sl.date_from, "date_to": sl.date_to,
                    "grain": grain, "date_column": sl.date_col},
        "explanation": _describe(sl, measure, agg, row_count, skipped),
        "sql": _display_sql(sl, headline_sql, own),
        "stats": stats,
        "trend": trend,
        "contributors": contributors,
        "dimensions": [{"name": d, "subtype": s, "pinned": d in sl.filters}
                       for d, s in sl.dimensions.items()],
        "measures": [{"name": m, "subtype": s} for m, s in sl.measures.items()],
        "additive": agg in _ADDITIVE,
        "notes": notes,
    }


def _contributors(con, sl: _Slice, measure, agg, vexpr, limit, total) -> list[dict]:
    """Every free dimension's split of the slice, from ONE scan.

    Splitting by each dimension separately costs a scan per dimension (three
    queries each, with the tail and the distinct count); on a 1M-row table
    with 20 dimensions that is most of a second. GROUPING SETS computes every
    dimension's groups in a single pass, and each group carries enough partial
    aggregates (rows, sum, count, min, max) to rebuild any of the decomposable
    aggregations — including the "other" tail — exactly. A median is not
    decomposable, so it keeps the per-dimension path.
    """
    dims = [d for d in sl.dimensions if d not in sl.filters]
    if not dims:
        return []
    if agg == "median":
        return [_split(con, sl, d, measure, agg, vexpr, limit, total) for d in dims]

    cols = [safe_identifier(d, sl.allowed) for d in dims]
    mq = safe_identifier(measure, sl.allowed) if measure else None
    parts = "COUNT(*)" + (f", SUM({mq}), COUNT({mq}), MIN({mq}), MAX({mq})" if mq else "")
    flags = ", ".join(f"GROUPING({c})" for c in cols)
    where, params, own = sl.where()
    rows = con.execute(
        f"SELECT {flags}, {', '.join(cols)}, {parts} FROM {sl.relation} {where} "
        f"GROUP BY GROUPING SETS ({', '.join(f'({c})' for c in cols)})", params,
    ).fetchall()

    k = len(dims)
    groups: dict[str, list] = {d: [] for d in dims}
    for r in rows:
        i = next(j for j in range(k) if r[j] == 0)       # the set this row belongs to
        name = r[k + i]
        if name is None:                                  # blank values are not a contributor
            continue
        n, s, c, lo, hi = (r[2 * k:] + (None,) * 4)[:5]
        groups[dims[i]].append({"name": name, "rows": n, "s": s, "c": c, "lo": lo, "hi": hi})

    def value_of(gs):
        if agg == "count":
            return sum(g["rows"] for g in gs)
        if agg == "sum":
            vals = [g["s"] for g in gs if g["s"] is not None]
            return sum(vals) if vals else None
        if agg == "avg":
            c = sum(g["c"] or 0 for g in gs)
            return (sum(g["s"] or 0 for g in gs) / c) if c else None
        bound = [g["lo" if agg == "min" else "hi"] for g in gs if g["lo"] is not None]
        return (min(bound) if agg == "min" else max(bound)) if bound else None

    additive = agg in _ADDITIVE
    share = lambda v: (round((v or 0) / total * 100, 1) if additive and total else None)  # noqa: E731
    out = []
    for dim, gq in zip(dims, cols):
        gs = groups[dim]
        for g in gs:
            g["value"] = value_of([g])
        gs.sort(key=lambda g: (g["value"] is None, -(g["value"] or 0), str(g["name"])))
        shown, tail = gs[:limit], gs[limit:]
        others = None
        if tail:
            ov = value_of(tail)
            others = {"count": len(tail), "value": ov, "rows": sum(g["rows"] for g in tail), "share_pct": share(ov)}
        dwhere, _, downs = sl.where(f"{gq} IS NOT NULL")
        shown_sql = (f"SELECT {gq} AS name, {vexpr} AS value, COUNT(*) AS n FROM {sl.relation} {dwhere} "
                     f"GROUP BY 1 ORDER BY value DESC NULLS LAST, name LIMIT {int(limit)}")
        out.append({
            "dimension": dim, "subtype": sl.dimensions.get(dim), "distinct": len(gs),
            "items": [{"name": g["name"], "value": g["value"], "rows": g["rows"], "share_pct": share(g["value"])}
                      for g in shown],
            "others": others,
            "sql": _display_sql(sl, shown_sql, downs),
        })
    return out


def _split(con, sl: _Slice, dim: str, measure, agg, vexpr, limit, total) -> dict:
    """One dimension of the slice, ranked, with the tail folded into `others`."""
    gq = safe_identifier(dim, sl.allowed)
    where, params, own = sl.where(f"{gq} IS NOT NULL")
    rel = sl.relation
    ranked_sql = (f"SELECT {gq} AS name, {vexpr} AS value, COUNT(*) AS n FROM {rel} {where} "
                  f"GROUP BY 1 ORDER BY value DESC NULLS LAST, name LIMIT {int(limit) + 1}")
    rows = con.execute(ranked_sql, params).fetchall()
    distinct = con.execute(f"SELECT COUNT(DISTINCT {gq}) FROM {rel} {where}", params).fetchone()[0]
    additive = agg in _ADDITIVE
    shown = rows[:limit]
    items = [{"name": r[0], "value": r[1], "rows": r[2],
              "share_pct": (round((r[1] or 0) / total * 100, 1) if additive and total else None)}
             for r in shown]
    others = None
    if distinct > len(shown):
        # the tail is computed in SQL, not as total-minus-shown, so it is right
        # for every aggregation (an average of the rest is not a difference)
        names = [r[0] for r in shown]
        marks = ", ".join("?" * len(names))
        owhere, oparams, _ = sl.where(f"{gq} IS NOT NULL AND {gq} NOT IN ({marks})" if names
                                      else f"{gq} IS NOT NULL")
        orow = con.execute(f"SELECT {vexpr}, COUNT(*) FROM {rel} {owhere}",
                           oparams + names).fetchone()
        others = {"count": distinct - len(shown), "value": orow[0], "rows": orow[1],
                  "share_pct": (round((orow[0] or 0) / total * 100, 1) if additive and total else None)}
    return {"dimension": dim, "subtype": sl.dimensions.get(dim), "distinct": distinct,
            "items": items, "others": others,
            "sql": _display_sql(sl, ranked_sql.replace(f"LIMIT {int(limit) + 1}", f"LIMIT {int(limit)}"), own)}


# -------------------------------------------------------------- breakdown ---

def breakdown(con, workspace_id, dataset_id, *, dimension, measure=None, agg="sum",
              filters=None, date_from=None, date_to=None, limit=50, user_id=None, public=False) -> dict:
    sl = _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to, public)
    if dimension not in sl.allowed or dimension == sl.date_col:
        raise DrillError(f"cannot break down by {dimension!r}")
    measure = _resolve_measure(sl, measure, agg)
    vexpr = _value_expr(sl, measure, agg)
    limit = max(1, min(int(limit), MAX_BREAKDOWN))
    where, params, _ = sl.where()
    total = con.execute(f"SELECT {vexpr} FROM {sl.relation} {where}", params).fetchone()[0]
    out = _split(con, sl, dimension, measure, agg, vexpr, limit, total)
    out.update({"measure": measure, "agg": agg,
                "subtype": sl.measures.get(measure) if agg != "count" else None,
                "dimension_subtype": sl.dimensions.get(dimension), "total": total,
                "additive": agg in _ADDITIVE})
    return out


# ---------------------------------------------------------------- records ---

def _jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def records(con, workspace_id, dataset_id, *, filters=None, date_from=None, date_to=None,
            sort=None, desc=True, page=1, page_size=50, user_id=None) -> dict:
    sl = _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to)
    names = [c.name for c in sl.columns]
    if sort is not None and sort not in sl.allowed:
        raise DrillError(f"cannot sort by {sort!r}")
    sort = sort or sl.date_col
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    page = max(1, int(page))

    where, params, _ = sl.where()
    total = con.execute(f"SELECT COUNT(*) FROM {sl.relation} {where}", params).fetchone()[0]
    select = ", ".join(safe_identifier(n, sl.allowed) for n in names)
    order = ""
    if sort:
        order = (f"ORDER BY {safe_identifier(sort, sl.allowed)} "
                 f"{'DESC' if desc else 'ASC'} NULLS LAST")
    rows = con.execute(
        f"SELECT {select} FROM {sl.relation} {where} {order} LIMIT {page_size} OFFSET {(page - 1) * page_size}",
        params,
    ).fetchall()
    return {
        "columns": [{"name": c.name, "role": c.role, "subtype": c.subtype} for c in sl.columns],
        "rows": [[_jsonable(v) for v in r] for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "sort": sort, "desc": bool(desc) if sort else None,
    }


def records_csv(con, workspace_id, dataset_id, *, filters=None, date_from=None, date_to=None,
                sort=None, desc=True, user_id=None) -> str:
    sl = _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to)
    if sort is not None and sort not in sl.allowed:
        raise DrillError(f"cannot sort by {sort!r}")
    select = ", ".join(safe_identifier(c.name, sl.allowed) for c in sl.columns)
    order = (f"ORDER BY {safe_identifier(sort, sl.allowed)} {'DESC' if desc else 'ASC'} NULLS LAST"
             if sort else "")
    where, params, _ = sl.where()
    return con.execute(f"SELECT {select} FROM {sl.relation} {where} {order}", params
                       ).df().to_csv(index=False)


def parse_filters(raw: str | None) -> dict:
    """Filters arrive as one JSON object (`{"region": "North"}`) rather than as
    bare query params, so a column called `page` or `sort` cannot collide with
    the endpoint's own parameters."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise DrillError("filters must be a JSON object")
    if not isinstance(data, dict):
        raise DrillError("filters must be a JSON object")
    return data

