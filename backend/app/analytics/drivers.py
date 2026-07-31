"""Root-cause / driver analysis — explain *why* a measure changed.

Deterministic decomposition of a measure's change between the two most recent
periods (months): the total delta is broken down by each dimension so you can
see which segments drove it ("revenue rose 12% — Delhi added ₹8k, Mumbai gave
back ₹2k"). Every number is computed from the data and the explanation sentence
is templated in code — no LLM, no invented figures. The "primary" dimension is
the one whose movements most concentrate the overall change.
"""

from ..core.sqlsafe import safe_identifier, safe_table_name
from .engine import get_columns, get_dataset
from .intelligence import format_value


class DriverError(ValueError):
    """Driver analysis could not run (e.g. non-structured dataset)."""


def _month_expr(dq: str) -> str:
    return f"strftime(date_trunc('month', TRY_CAST({dq} AS TIMESTAMP)), '%Y-%m')"


def _trim(drivers: list, n: int) -> list:
    """Keep the n biggest movers (by magnitude), shown gainers-first."""
    movers = sorted(drivers, key=lambda x: abs(x["delta"]), reverse=True)[:n]
    movers.sort(key=lambda x: x["delta"], reverse=True)
    return movers


def explain_change(con, workspace_id, dataset_id, measure=None, dimension=None, max_drivers=6) -> dict:
    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DriverError("driver analysis only applies to structured datasets")
    cols = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in cols}
    measures = [c for c in cols if c.role == "measure"]
    if not measures:
        return {"available": False, "reason": "no numeric measure to analyse"}

    measure_names = {m.name for m in measures}
    meas = measure if measure in measure_names else measures[0].name
    subtype = next((c.subtype for c in cols if c.name == meas), None)
    date_col = next((c.name for c in cols if c.role == "date"), None)
    if not date_col:
        return {"available": False, "reason": "no date column, so periods can't be compared"}

    tq = safe_table_name(dataset["table_name"])
    mq = safe_identifier(meas, allowed)
    dq = safe_identifier(date_col, allowed)
    mexpr = _month_expr(dq)

    months = con.execute(
        f"SELECT {mexpr} m, sum({mq}) v FROM {tq} WHERE TRY_CAST({dq} AS TIMESTAMP) IS NOT NULL "
        f"GROUP BY 1 ORDER BY 1"
    ).fetchall()
    months = [(m, v) for m, v in months if m is not None]
    if len(months) < 2:
        return {"available": False, "reason": "need at least two months of data to explain a change"}

    (prev_m, prev_total), (curr_m, curr_total) = months[-2], months[-1]
    prev_total, curr_total = float(prev_total or 0), float(curr_total or 0)
    delta = curr_total - prev_total
    pct = (delta / prev_total * 100.0) if prev_total else None

    dims = [c.name for c in cols if c.role == "dimension"]
    if dimension:
        dims = [dimension] if (dimension in dims) else dims

    dim_results = {}
    for d in dims:
        gq = safe_identifier(d, allowed)
        rows = con.execute(
            f"SELECT {mexpr} m, {gq} g, sum({mq}) v FROM {tq} "
            f"WHERE {mexpr} IN (?, ?) AND {gq} IS NOT NULL GROUP BY 1, 2",
            [prev_m, curr_m],
        ).fetchall()
        agg = {}
        for m, g, v in rows:
            slot = agg.setdefault(g, {"previous": 0.0, "current": 0.0})
            if m == prev_m:
                slot["previous"] = float(v or 0)
            elif m == curr_m:
                slot["current"] = float(v or 0)
        drivers = [
            {"name": g, "previous": s["previous"], "current": s["current"],
             "delta": s["current"] - s["previous"],
             "share": ((s["current"] - s["previous"]) / delta) if delta else None}
            for g, s in agg.items()
        ]
        concentration = (max((abs(x["delta"]) for x in drivers), default=0.0) / abs(delta)) if delta else 0.0
        dim_results[d] = {"drivers": _trim(drivers, max_drivers), "concentration": concentration}

    primary = max(dim_results, key=lambda d: dim_results[d]["concentration"]) if dim_results else None
    result = {
        "available": True, "measure": meas, "subtype": subtype,
        "previous_period": prev_m, "current_period": curr_m,
        "previous_total": prev_total, "current_total": curr_total,
        "delta": delta, "pct_change": pct,
        "primary_dimension": primary, "dimensions": dim_results,
    }
    result["summary"] = _summarize(result)
    return result


def _summarize(r: dict) -> str:
    meas = r["measure"].replace("_", " ")
    d, sub = r["delta"], r["subtype"]
    direction = "rose" if d > 0 else "fell" if d < 0 else "was flat"
    sign = "+" if d > 0 else "−"

    head = f"{meas[:1].upper()}{meas[1:]} {direction}"
    if r["pct_change"] is not None and d != 0:
        head += f" {abs(r['pct_change']):.1f}% ({sign}{format_value(abs(d), sub)})"
    head += f" from {r['previous_period']} to {r['current_period']}"

    prim = r["primary_dimension"]
    if prim and d != 0 and r["dimensions"].get(prim, {}).get("drivers"):
        drivers = r["dimensions"][prim]["drivers"]
        gain = max(drivers, key=lambda x: x["delta"])
        loss = min(drivers, key=lambda x: x["delta"])
        clauses = []
        if gain["delta"] > 0:
            frag = f"driven mainly by {gain['name']} (+{format_value(gain['delta'], sub)}"
            if gain.get("share") is not None:
                frag += f", {abs(gain['share']) * 100:.0f}% of the move"
            clauses.append(frag + ")")
        if loss["delta"] < 0 and loss["name"] != gain["name"]:
            clauses.append(f"partly offset by {loss['name']} (−{format_value(abs(loss['delta']), sub)})")
        if clauses:
            head += ", " + "; ".join(clauses)
    return head + "."
