"""Metric tree — why a certified metric moved, in terms of its parts.

A certified ratio (gross margin = SUM(profit) / SUM(revenue)) can rise because
its numerator grew or because its denominator shrank, and those call for very
different actions. Between periods A and B the change splits exactly:

    numerator effect   = (N_b - N_a) / D_a           the ratio at A's denominator
    denominator effect = N_b / D_b - N_b / D_a       then the denominator moves

The two add up to r_b - r_a. Each part is itself a plain aggregate, so the
response says which measure to open next (and the UI opens it in the "why it
changed" view) — a tree you can keep descending.

An aggregate metric is a single node: its A, B and change.
"""

from ..core.sqlsafe import safe_identifier
from .drill import _date_bounds, _open
from .semantic import MetricError, _agg_sql, _get_metric
from .variance import _label, _periods


def _component(spec: dict, measures: dict) -> dict:
    """What a numerator/denominator spec is, and where to drill into it."""
    col, agg = spec.get("column"), spec.get("agg")
    drillable = agg == "sum" and col in measures
    return {"agg": agg, "column": col, "drill": {"measure": col, "agg": "sum"} if drillable else
            ({"agg": "count"} if agg == "count" else None)}


def explain_metric(con, workspace_id, metric_id, *, grain="month", compare="previous", user_id=None) -> dict:
    metric = _get_metric(con, workspace_id, metric_id)
    dataset_id = metric["dataset_id"]
    sl = _open(con, workspace_id, dataset_id, user_id, None, None, None)
    per = _periods(con, sl, grain, compare)
    pa, pb = per["a"], per["b"]
    ts = f"TRY_CAST({safe_identifier(sl.date_col, sl.allowed)} AS TIMESTAMP)"

    def in_period(expr_sql: str, p) -> float | None:
        lo, _ = _date_bounds(p[0].isoformat(), None)
        _, hi = _date_bounds(None, p[1].isoformat())
        where, params, _ = sl.where(f"{ts} >= ? AND {ts} < ?", dates=False)
        v = con.execute(f"SELECT {expr_sql} FROM {sl.relation} {where}", params + [lo, hi]).fetchone()[0]
        return None if v is None else float(v)

    scale = 100.0 if metric.get("format") == "percent" else 1.0
    base = {
        "metric_id": metric_id, "name": metric["name"], "kind": metric["kind"], "format": metric.get("format"),
        "a": {"label": _label(*pa), "from": pa[0].isoformat(), "to": pa[1].isoformat()},
        "b": {"label": _label(*pb), "from": pb[0].isoformat(), "to": pb[1].isoformat()},
        "like_for_like": per["like_for_like"],
    }

    if metric["kind"] == "aggregate":
        expr = _agg_sql(metric["definition"], sl.allowed)
        va, vb = in_period(expr, pa), in_period(expr, pb)
        base["a"]["value"], base["b"]["value"] = va, vb
        base["delta"] = (vb - va) if va is not None and vb is not None else None
        base["component"] = _component(metric["definition"], sl.measures)
        return base

    if metric["kind"] != "ratio":
        raise MetricError(f"unknown metric kind {metric['kind']!r}")
    num_spec, den_spec = metric["definition"]["numerator"], metric["definition"]["denominator"]
    n_sql, d_sql = _agg_sql(num_spec, sl.allowed), _agg_sql(den_spec, sl.allowed)
    na, nb, da, db = in_period(n_sql, pa), in_period(n_sql, pb), in_period(d_sql, pa), in_period(d_sql, pb)
    if not da or not db or na is None or nb is None:
        raise MetricError("the denominator is zero or missing in one of the periods, so the ratio has no change to explain")
    ra, rb = na / da, nb / db
    num_effect = (nb - na) / da
    den_effect = nb / db - nb / da
    base["a"].update({"value": ra * scale, "numerator": na, "denominator": da})
    base["b"].update({"value": rb * scale, "numerator": nb, "denominator": db})
    base["delta"] = (rb - ra) * scale
    base["numerator"] = {**_component(num_spec, sl.measures), "a": na, "b": nb, "effect": num_effect * scale,
                         "subtype": sl.measures.get(num_spec.get("column"))}
    base["denominator"] = {**_component(den_spec, sl.measures), "a": da, "b": db, "effect": den_effect * scale,
                           "subtype": sl.measures.get(den_spec.get("column"))}
    lead = "numerator" if abs(num_effect) >= abs(den_effect) else "denominator"
    part = base[lead]
    what = (part["column"] or "rows").replace("_", " ")
    moved = "rose" if part["b"] > part["a"] else "fell"
    base["summary"] = (f"{metric['name']} moved mostly because {what} {moved} "
                       f"({'numerator' if lead == 'numerator' else 'denominator'} of the ratio).")
    return base

