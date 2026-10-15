"""Recommended actions — what an analyst would tell you to do next.

Every recommendation is a rule over numbers this module computes from the
data, never generated text: the "why" sentence is a template filled with
those numbers, and each item carries the exact drill slice ("evidence") that
reproduces them, so the UI can open the proof in one click. A rule that cannot
be evaluated (no date column, no quantity measure) is skipped, not guessed.

Rules, in the order an analyst would raise them:
  * unusual_move      the latest change is outside the series' normal swing
  * target            a current-period target is at risk or off track
  * declining_segment a material segment fell 15%+ and drove the change
  * price_erosion     price changes alone took a material bite out of value
  * concentration     one value is 40%+ of the total and at least 1.5x an even
                      share (40% of three products is not a dependency)
  * missing_values    5%+ of rows have no value for the measure
  * growing_segment   a material segment grew 20%+ (something to repeat)
"""

from ..core.sqlsafe import safe_identifier
from .drill import DrillError, _contributors, _open, _resolve_measure
from .intelligence import format_value
from .targets import list_targets
from .variance import explain_variance, guess_volume_measure, price_volume_mix

SEVERITY = {"high": 0, "medium": 1, "low": 2}
DECLINE, GROWTH, MATERIAL = -0.15, 0.20, 0.05
CONCENTRATION = 40.0
FAIR_SHARE_MULTIPLE = 1.5
MISSING = 0.05


def _human(name: str) -> str:
    return (name or "").replace("_", " ")


def _pct(x) -> str:
    return f"{x * 100:+.0f}%"


def recommend(con, workspace_id, dataset_id, *, measure=None, filters=None, user_id=None,
              limit=8, public=False) -> dict:
    """`public=True` when the result leaves the app (an emailed report): the
    numbers are the author's, but any value they name is PII-masked."""
    sl = _open(con, workspace_id, dataset_id, user_id, filters, None, None, public)
    measure = _resolve_measure(sl, measure, "sum")
    if measure not in sl.measures:
        raise DrillError(f"{measure!r} is not a numeric measure")
    sub = sl.measures.get(measure)
    M = _human(measure).capitalize()
    fv = lambda v: format_value(v, sub)  # noqa: E731
    out: list[dict] = []
    checked: list[str] = []

    def add(kind, key, severity, title, why, action, evidence, magnitude=0.0):
        out.append({"id": f"{kind}:{key}", "kind": kind, "severity": severity, "title": title,
                     "why": why, "action": action, "magnitude": abs(magnitude or 0),
                     "evidence": {"measure": measure, "agg": "sum", "filters": dict(sl.filters), **evidence}})

    # ---- the latest change, and the segments behind it ----
    v = None
    if sl.date_col:
        try:
            v = explain_variance(con, workspace_id, dataset_id, measure=measure, filters=sl.filters, public=public,
                                 limit=25, user_id=user_id)
        except DrillError:
            v = None
    if v:
        checked += ["unusual_move", "declining_segment", "growing_segment"]
        sig, delta = v.get("significance"), v["delta"]
        if sig and sig["level"] != "normal" and delta:
            add("unusual_move", measure, "high" if sig["level"] == "unusual" else "medium",
                f"Investigate the {'drop' if delta < 0 else 'jump'} in {_human(measure)}",
                f"{M} {'fell' if delta < 0 else 'rose'} {fv(abs(delta))} from {v['a']['label']} to "
                f"{v['b']['label']} — {abs(sig['z']):.1f}× its typical {v['grain']}-to-{v['grain']} swing "
                f"of {fv(sig['typical_change'])}.",
                "Open the change breakdown and confirm which segments drove it before acting on it.",
                {"tab": "change", "compare": "previous"}, delta)
        dim, total_a, total_b = v["dimension"], v["a"]["value"], v["b"]["value"]
        for s in v["steps"]:
            if s["blank"] or not s["a"]:
                continue
            change = s["delta"] / abs(s["a"])
            name = str(s["name"])
            seg = {"filters": {**sl.filters, dim: name}}
            if change <= DECLINE and total_a and s["a"] / total_a >= MATERIAL:
                share = f", {abs(s['share_of_change']) * 100:.0f}% of the overall change" \
                    if s.get("share_of_change") is not None and delta < 0 else ""
                add("declining_segment", f"{dim}={name}", "high" if change <= -0.3 else "medium",
                    f"Find out why {name} is falling",
                    f"{_human(dim).capitalize()} {name}: {fv(s['a'])} → {fv(s['b'])} ({_pct(change)}) "
                    f"from {v['a']['label']} to {v['b']['label']}{share}.",
                    f"Look at {name}'s own breakdown and rows for the cause — stock, pricing, a lost account.",
                    {**seg, "tab": "change", "compare": "previous"}, s["delta"])
            elif change >= GROWTH and total_b and s["b"] / total_b >= MATERIAL:
                add("growing_segment", f"{dim}={name}", "low",
                    f"Build on {name}'s growth",
                    f"{_human(dim).capitalize()} {name}: {fv(s['a'])} → {fv(s['b'])} ({_pct(change)}).",
                    f"Find what is working in {name} and whether it can be repeated in other "
                    f"{_human(dim)} values.",
                    {**seg, "tab": "change", "compare": "previous"}, s["delta"])

    # ---- targets for the current period ----
    checked.append("target")
    for t in list_targets(con, workspace_id, dataset_id, user_id):
        if t.get("measure") != measure or t.get("filters") != sl.filters or not t.get("current"):
            continue
        if t["status"] in ("at_risk", "off_track"):
            add("target", t["target_id"], "high" if t["status"] == "off_track" else "medium",
                f"Close the gap on the {t['period']} target",
                f"At the current pace {_human(measure)} reaches {fv(t['projection'])} against a target of "
                f"{fv(t['value'])} ({t['projected_ratio'] * 100:.0f}%).",
                f"The remaining {t['days_remaining']} day{'s' if t['days_remaining'] != 1 else ''} need "
                f"{fv(t['needed_per_day'])} a day on average.",
                {"date_from": t["from"], "date_to": t["to"], "tab": "overview"}, t["gap"])

    # ---- price erosion ----
    if v and guess_volume_measure(sl.measures, measure):
        checked.append("price_erosion")
        try:
            p = price_volume_mix(con, workspace_id, dataset_id, measure=measure, filters=sl.filters, public=public,
                                 user_id=user_id)
        except DrillError:
            p = None
        if p:
            price = p["effects"]["price"]
            if price < 0 and (abs(price) >= 0.25 * abs(p["delta"] or 1) or abs(price) >= 0.02 * abs(p["a"]["value"])):
                worst = min(p["segments"], key=lambda s: s["price"]) if p["segments"] else None
                where = (f", most of it in {worst['name']}" if worst and worst["price"] < 0 and worst["name"] is not None
                         else "")
                add("price_erosion", measure, "medium", "Review pricing and discounts",
                    f"The average price went from {fv(p['a']['avg_price'])} to {fv(p['b']['avg_price'])} "
                    f"({_human(measure)} per {_human(p['volume'])}); price changes alone cost "
                    f"{fv(abs(price))} of {_human(measure)}{where}.",
                    "Check discounting and price changes before chasing more volume.",
                    {"tab": "change", "compare": "previous"}, price)

    # ---- concentration ----
    checked.append("concentration")
    vexpr = f"SUM({safe_identifier(measure, sl.allowed)})"
    where, params, _ = sl.where()
    total = con.execute(f"SELECT {vexpr} FROM {sl.relation} {where}", params).fetchone()[0]
    best = None
    for split in (_contributors(con, sl, measure, "sum", vexpr, 1, total) if total else []):
        dim = split["dimension"]
        if split["items"] and split["distinct"] >= 3:
            top = split["items"][0]
            bar = max(CONCENTRATION, FAIR_SHARE_MULTIPLE * 100.0 / split["distinct"])
            if top["share_pct"] is not None and top["share_pct"] >= bar and (
                    best is None or top["share_pct"] > best[1]["share_pct"]):
                best = (dim, top, split["distinct"])
    if best:
        dim, top, n = best
        add("concentration", f"{dim}={top['name']}", "medium",
            f"Reduce dependence on {top['name']}",
            f"{top['name']} is {top['share_pct']:.0f}% of all {_human(measure)} across {n} "
            f"{_human(dim)} values.",
            f"Protect {top['name']} and grow the others — a problem there hits the whole business.",
            {"filters": {**sl.filters, dim: str(top["name"])}, "tab": "overview"}, total * top["share_pct"] / 100)

    # ---- data completeness ----
    checked.append("missing_values")
    mq = safe_identifier(measure, sl.allowed)
    rows, missing = con.execute(f"SELECT COUNT(*), COUNT(*) - COUNT({mq}) FROM {sl.relation} {where}",
                                params).fetchone()
    if rows and missing / rows >= MISSING:
        add("missing_values", measure, "medium", f"Fill in missing {_human(measure)}",
            f"{missing:,} of {rows:,} rows ({missing / rows * 100:.0f}%) have no {_human(measure)}, "
            "so every total understates it.",
            "Fix the source data or exclude those rows knowingly — see Data quality.",
            {"tab": "records"}, missing)

    out.sort(key=lambda a: (SEVERITY[a["severity"]], -a["magnitude"]))
    return {"measure": measure, "subtype": sub, "filters": sl.filters,
            "actions": out[:max(1, min(int(limit), 20))], "checked": checked}
