"""Variance analysis — *why* a number moved between two periods.

Built on the drill slice (measure + filters), three answers:

  * `explain_variance` — the change from period A to period B, split by one
    dimension into a waterfall that reconciles to the cent: start, one step per
    member (the long tail folded into "other"), end. With no dimension given,
    every dimension is scored and the one whose movement is most concentrated
    is chosen — the "biggest mover" split a decomposition tree descends by.
  * `price_volume_mix` — for a value measure that is volume x price (revenue =
    units x price), the change is split into a volume effect, a mix effect and
    a price effect. The three add up exactly; anything the data cannot explain
    that way (value recorded without volume) is reported as `unexplained`
    rather than hidden.

Periods: B is the slice's own date range, or the latest period at the chosen
grain; A is the period before it, or the same period a year earlier. When the
data stops partway through B, A is cut to the same number of days — a
28-day October is compared with the first 28 days of September, never with
all 30 of it. That one rule removes the most common false "drop" in BI.

Every figure is plain SQL over the member's secured relation (row rules and
masking apply); nothing here is estimated.
"""

import calendar
from datetime import date, timedelta

from ..core.sqlsafe import safe_identifier
from .drill import DrillError, _date_bounds, _open, _resolve_measure

COMPARES = ("previous", "year_ago")
_ADDITIVE = ("sum", "count")
MAX_STEPS = 25

# a column named like this is a volume, so revenue / it is a price
_VOLUME_HINTS = ("unit", "qty", "quantity", "volume", "orders", "items", "count", "sold", "pieces")


# ------------------------------------------------------------ periods ---

def _first(s: str) -> date:
    parts = [int(p) for p in s.split("-")]
    return date(parts[0], parts[1], parts[2] if len(parts) == 3 else 1)


def _last(s: str) -> date:
    parts = [int(p) for p in s.split("-")]
    if len(parts) == 3:
        return date(*parts)
    return date(parts[0], parts[1], calendar.monthrange(parts[0], parts[1])[1])


def _add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _minus_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:          # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def shift_period(b0: date, b1: date, compare: str) -> tuple[date, date]:
    """The comparison period A for B = [b0, b1] (inclusive)."""
    aligned = b0.day == 1 and b1 == _month_end(b1)
    if aligned:
        months = (b1.year - b0.year) * 12 + b1.month - b0.month + 1
        k = 12 if compare == "year_ago" else months
        a0 = _add_months(b0, -k)
        return a0, _month_end(_add_months(b1.replace(day=1), -k))
    if compare == "year_ago":
        return _minus_year(b0), _minus_year(b1)
    n = (b1 - b0).days + 1
    return b0 - timedelta(days=n), b0 - timedelta(days=1)


def latest_period(d: date, grain: str) -> tuple[date, date]:
    """The whole period at `grain` that contains day `d` (weeks start Monday)."""
    if grain == "day":
        return d, d
    if grain == "week":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if grain == "month":
        return d.replace(day=1), _month_end(d)
    if grain == "quarter":
        first = (d.month - 1) // 3 * 3 + 1
        return date(d.year, first, 1), _month_end(date(d.year, first + 2, 1))
    if grain == "year":
        return date(d.year, 1, 1), date(d.year, 12, 31)
    raise DrillError(f"unknown grain {grain!r}")


def _label(d0: date, d1: date) -> str:
    if d0.day == 1 and d1 == _month_end(d1):
        if (d0.year, d0.month) == (d1.year, d1.month):
            return d0.strftime("%b %Y")
        return f"{d0.strftime('%b %Y')} – {d1.strftime('%b %Y')}"
    if d0 == d1:
        return d0.strftime("%d %b %Y").lstrip("0")
    return f"{d0.strftime('%d %b').lstrip('0')} – {d1.strftime('%d %b %Y').lstrip('0')}"


def _periods(con, sl, grain: str, compare: str) -> dict:
    if compare not in COMPARES:
        raise DrillError(f"unknown comparison {compare!r}")
    if not sl.date_col:
        raise DrillError("this dataset has no date column, so periods can't be compared")
    dq = safe_identifier(sl.date_col, sl.allowed)
    data_end = con.execute(f"SELECT MAX(TRY_CAST({dq} AS TIMESTAMP)) FROM {sl.relation}",
                           list(sl.rls_params)).fetchone()[0]
    if data_end is None:
        raise DrillError("no dated rows to compare")
    data_end = date.fromisoformat(str(data_end)[:10])

    if sl.date_from or sl.date_to:
        b0 = _first(sl.date_from) if sl.date_from else None
        b1 = _last(sl.date_to) if sl.date_to else data_end
        if b0 is None:
            raise DrillError("comparing needs a start date")
    else:
        b0, b1 = latest_period(data_end, grain)
    # B is exactly one period at this grain: its history is a like-for-like
    # series, which is what makes "is this change unusual?" answerable
    aligned = latest_period(b0, grain) == (b0, b1)

    a0, a1 = shift_period(b0, b1, compare)
    like_for_like = False
    if data_end < b1:
        # cut both to the days that actually exist in B
        days = (data_end - b0).days
        if days < 0:
            raise DrillError("the chosen period has no data yet")
        b1 = data_end
        a1 = min(a1, a0 + timedelta(days=days))
        like_for_like = True
    return {"a": (a0, a1), "b": (b0, b1), "like_for_like": like_for_like,
            "data_end": data_end.isoformat(), "aligned": aligned}


# ------------------------------------------------------- significance ---

MIN_HISTORY = 5
_STEP_MONTHS = {"month": 1, "quarter": 3, "year": 12}


def _next_period(d: date, grain: str) -> date:
    if grain == "day":
        return d + timedelta(days=1)
    if grain == "week":
        return d + timedelta(days=7)
    return _add_months(d, _STEP_MONTHS[grain])


def _significance(con, sl, measure, agg, grain, per) -> dict | None:
    """Is the latest period-over-period change bigger than this series
    usually moves? Each earlier period is measured over the same window (the
    first N days when B is partial), so the changes being compared are like
    for like. Returns None when there is too little history to say."""
    if not per["aligned"]:
        return None
    b0, b1 = per["b"]
    dq = safe_identifier(sl.date_col, sl.allowed)
    ts = f"TRY_CAST({dq} AS TIMESTAMP)"
    trunc = f"date_trunc('{grain}', {ts})"          # grain is one of the fixed GRAINS
    val = "1" if agg == "count" else safe_identifier(measure, sl.allowed)
    window = (b1 - b0).days + 1 if per["like_for_like"] else 400
    _, b_end = _date_bounds(None, b1.isoformat())
    where, params, _ = sl.where(f"{ts} IS NOT NULL AND {ts} < ? AND date_diff('day', {trunc}, {ts}) < ?",
                                dates=False)
    rows = con.execute(f"SELECT CAST({trunc} AS DATE) AS p, SUM({val}) FROM {sl.relation} {where} "
                       f"GROUP BY 1 ORDER BY 1", params + [b_end, window]).fetchall()
    if not rows:
        return None
    found = {r[0]: float(r[1] or 0) for r in rows}
    # a period with no rows is a real zero, not a gap to skip over
    values, d = [], rows[0][0]
    while d <= b0:
        values.append(found.get(d, 0.0))
        d = _next_period(d, grain)
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    if len(deltas) < MIN_HISTORY + 1:
        return None
    latest, history = deltas[-1], deltas[:-1]
    mean = sum(history) / len(history)
    std = (sum((x - mean) ** 2 for x in history) / (len(history) - 1)) ** 0.5
    if std == 0:
        return None
    z = (latest - mean) / std
    level = "unusual" if abs(z) >= 2.5 else "notable" if abs(z) >= 1.5 else "normal"
    return {"level": level, "z": z, "typical_change": std, "mean_change": mean,
            "history": len(history), "window_days": window if per["like_for_like"] else None}


# --------------------------------------------------------- variance ------

def _period_sql(sl, measure, agg):
    """SQL for 'value in A' and 'value in B' as conditional aggregates, and the
    params they need (A bounds then B bounds, repeated per use)."""
    dq = safe_identifier(sl.date_col, sl.allowed)
    ts = f"TRY_CAST({dq} AS TIMESTAMP)"
    if agg == "count":
        val = "1"
    else:
        val = safe_identifier(measure, sl.allowed)
    in_a = f"{ts} >= ? AND {ts} < ?"
    in_b = in_a
    a_expr = f"SUM(CASE WHEN {in_a} THEN {val} ELSE 0 END)"
    b_expr = f"SUM(CASE WHEN {in_b} THEN {val} ELSE 0 END)"
    window = f"(({in_a}) OR ({in_b}))"
    return a_expr, b_expr, window


def _bounds(p):
    lo, _ = _date_bounds(p[0].isoformat(), None)
    _, hi = _date_bounds(None, p[1].isoformat())
    return [lo, hi]


def _member_rows(con, sl, dims, measure, agg, pa, pb) -> dict:
    """{dimension: [(member, value in A, value in B), ...]} for every dimension
    from ONE scan (GROUPING SETS) rather than one scan per dimension — the
    ranking below needs them all, and on a wide table that was the cost."""
    cols = [safe_identifier(d, sl.allowed) for d in dims]
    a_expr, b_expr, window = _period_sql(sl, measure, agg)
    where, params, _ = sl.where(window, dates=False)
    flags = ", ".join(f"GROUPING({c})" for c in cols)
    rows = con.execute(
        f"SELECT {flags}, {', '.join(cols)}, {a_expr}, {b_expr} FROM {sl.relation} {where} "
        f"GROUP BY GROUPING SETS ({', '.join(f'({c})' for c in cols)})",
        _bounds(pa) + _bounds(pb) + params + _bounds(pa) + _bounds(pb),
    ).fetchall()
    k = len(dims)
    out = {d: [] for d in dims}
    for r in rows:
        i = next(j for j in range(k) if r[j] == 0)
        out[dims[i]].append((r[k + i], r[2 * k], r[2 * k + 1]))
    return out


def _split_change(dim, rows, limit):
    """Per-member A, B, delta for one dimension — NULL members kept, so the
    steps always add up to the total change."""
    members = [{"name": g, "blank": g is None, "a": float(a or 0), "b": float(b or 0)} for g, a, b in rows]
    for m in members:
        m["delta"] = m["b"] - m["a"]
    moved = [m for m in members if m["delta"] != 0]
    total_abs = sum(abs(m["delta"]) for m in moved)
    score = (max(abs(m["delta"]) for m in moved) / total_abs) if (total_abs and len(moved) >= 2) else 0.0

    ranked = sorted(members, key=lambda m: abs(m["delta"]), reverse=True)
    shown, rest = ranked[:limit], ranked[limit:]
    shown.sort(key=lambda m: m["delta"], reverse=True)
    other = None
    if rest:
        other = {"count": len(rest), "a": sum(m["a"] for m in rest), "b": sum(m["b"] for m in rest),
                 "delta": sum(m["delta"] for m in rest)}
    return {"dimension": dim, "members": len(members), "score": score,
            "top": ranked[0] if ranked else None, "steps": shown, "other": other}


def explain_variance(con, workspace_id, dataset_id, *, measure=None, agg="sum", filters=None,
                     date_from=None, date_to=None, grain="month", compare="previous",
                     dimension=None, limit=8, user_id=None, public=False) -> dict:
    sl = _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to, public)
    if agg not in _ADDITIVE:
        raise DrillError("a change can only be broken into parts for a total or a count")
    measure = _resolve_measure(sl, measure, agg)
    if agg != "count" and measure not in sl.measures:
        raise DrillError(f"{measure!r} is not a numeric measure")
    limit = max(1, min(int(limit), MAX_STEPS))
    per = _periods(con, sl, grain, compare)
    pa, pb = per["a"], per["b"]

    a_expr, b_expr, window = _period_sql(sl, measure, agg)
    where, params, _ = sl.where(window, dates=False)
    ta, tb = con.execute(f"SELECT {a_expr}, {b_expr} FROM {sl.relation} {where}",
                         _bounds(pa) + _bounds(pb) + params + _bounds(pa) + _bounds(pb)).fetchone()
    ta, tb = float(ta or 0), float(tb or 0)
    delta = tb - ta

    candidates = [d for d in sl.dimensions if d not in sl.filters]
    if dimension is not None and dimension not in candidates:
        raise DrillError(f"cannot split by {dimension!r}")
    # score every candidate so the UI can offer "best explained by …" choices
    member_rows = _member_rows(con, sl, candidates, measure, agg, pa, pb) if candidates else {}
    splits = {d: _split_change(d, member_rows[d], limit) for d in candidates}
    ranking = sorted(({"dimension": d, "score": s["score"], "top": s["top"]["name"] if s["top"] else None,
                       "top_delta": s["top"]["delta"] if s["top"] else 0}
                      for d, s in splits.items()), key=lambda r: r["score"], reverse=True)
    auto = ranking[0]["dimension"] if ranking and ranking[0]["score"] > 0 else (candidates[0] if candidates else None)
    chosen = dimension or auto
    split = splits.get(chosen)

    steps = []
    if split:
        for m in split["steps"]:
            steps.append({**m, "share_of_change": (m["delta"] / delta) if delta else None})
    other = split["other"] if split else None
    if other:
        other["share_of_change"] = (other["delta"] / delta) if delta else None

    subtype = sl.measures.get(measure) if agg != "count" else None
    pct = (delta / abs(ta) * 100.0) if ta else None
    result = {
        "measure": measure, "agg": agg, "subtype": subtype, "compare": compare, "grain": grain,
        "a": {"from": pa[0].isoformat(), "to": pa[1].isoformat(), "label": _label(*pa), "value": ta},
        "b": {"from": pb[0].isoformat(), "to": pb[1].isoformat(), "label": _label(*pb), "value": tb},
        "delta": delta, "pct": pct,
        "like_for_like": per["like_for_like"], "data_end": per["data_end"],
        "dimension": chosen, "auto_dimension": auto, "ranking": ranking,
        "steps": steps, "other": other,
        "members": split["members"] if split else 0,
        "filters": sl.filters,
        # only meaningful against the previous period; a year-ago gap has no
        # series of comparable changes behind it
        "significance": _significance(con, sl, measure, agg, grain, per) if compare == "previous" else None,
    }
    result["summary"] = _summary(result)
    if per["like_for_like"]:
        result["note"] = (f"The data ends on {per['data_end']}, so {result['b']['label']} is compared "
                          f"with the same number of days of {result['a']['label']} (like for like).")
    return result


def _fmt(v, subtype):
    from .intelligence import format_value
    return format_value(v, subtype)


def _summary(r: dict) -> str:
    name = "Row count" if r["agg"] == "count" else r["measure"].replace("_", " ").capitalize()
    d, sub = r["delta"], r["subtype"]
    if d == 0:
        return f"{name} was unchanged between {r['a']['label']} and {r['b']['label']}."
    verb = "rose" if d > 0 else "fell"
    text = f"{name} {verb} "
    if r["pct"] is not None:
        text += f"{abs(r['pct']):.1f}% "
    text += f"({'+' if d > 0 else '−'}{_fmt(abs(d), sub)}) from {r['a']['label']} to {r['b']['label']}"
    if r["steps"] and r["dimension"]:
        lead = max(r["steps"], key=lambda s: abs(s["delta"]) if (s["delta"] > 0) == (d > 0) else -1)
        if (lead["delta"] > 0) == (d > 0) and lead["delta"] != 0 and not lead["blank"]:
            share = abs(lead["delta"] / d) * 100
            text += (f" — {r['dimension'].replace('_', ' ')} {lead['name']} accounts for "
                     f"{'+' if lead['delta'] > 0 else '−'}{_fmt(abs(lead['delta']), sub)} ({share:.0f}% of the move)")
    return text + "."


# ------------------------------------------------- price / volume / mix --

def guess_volume_measure(measures: dict, value_measure: str | None) -> str | None:
    for name in measures:
        if name != value_measure and any(h in name.lower() for h in _VOLUME_HINTS):
            return name
    return None


def price_volume_mix(con, workspace_id, dataset_id, *, measure=None, volume=None, filters=None,
                     date_from=None, date_to=None, grain="month", compare="previous",
                     dimension=None, limit=8, user_id=None, public=False) -> dict:
    sl = _open(con, workspace_id, dataset_id, user_id, filters, date_from, date_to, public)
    measure = _resolve_measure(sl, measure, "sum")
    if measure not in sl.measures:
        raise DrillError(f"{measure!r} is not a numeric measure")
    volume = volume or guess_volume_measure(sl.measures, measure)
    if not volume:
        raise DrillError("choose the volume measure (e.g. units) that the value is a multiple of")
    if volume not in sl.measures or volume == measure:
        raise DrillError(f"{volume!r} cannot be the volume for {measure!r}")
    candidates = [d for d in sl.dimensions if d not in sl.filters]
    if dimension is None and candidates:
        dimension = next((d for d in candidates if any(h in d.lower() for h in ("product", "sku", "item", "category"))),
                         candidates[0])
    elif dimension is not None and dimension not in candidates:
        raise DrillError(f"cannot analyse the mix across {dimension!r}")
    per = _periods(con, sl, grain, compare)
    pa, pb = per["a"], per["b"]

    # drilled all the way down there is nothing to mix across: one segment,
    # so the change is volume and price alone (mix is zero by construction)
    gq = safe_identifier(dimension, sl.allowed) if dimension else "NULL"
    vq = safe_identifier(measure, sl.allowed)
    qq = safe_identifier(volume, sl.allowed)
    ts = f"TRY_CAST({safe_identifier(sl.date_col, sl.allowed)} AS TIMESTAMP)"
    in_p = f"{ts} >= ? AND {ts} < ?"
    where, params, _ = sl.where(f"(({in_p}) OR ({in_p}))", dates=False)
    rows = con.execute(
        f"SELECT {gq}, "
        f"SUM(CASE WHEN {in_p} THEN {vq} ELSE 0 END), SUM(CASE WHEN {in_p} THEN {qq} ELSE 0 END), "
        f"SUM(CASE WHEN {in_p} THEN {vq} ELSE 0 END), SUM(CASE WHEN {in_p} THEN {qq} ELSE 0 END) "
        f"FROM {sl.relation} {where} GROUP BY 1",
        _bounds(pa) * 2 + _bounds(pb) * 2 + params + _bounds(pa) + _bounds(pb),
    ).fetchall()
    seg = [{"name": g, "ra": float(ra or 0), "qa": float(qa or 0), "rb": float(rb or 0), "qb": float(qb or 0)}
           for g, ra, qa, rb, qb in rows]
    Ra, Qa = sum(s["ra"] for s in seg), sum(s["qa"] for s in seg)
    Rb, Qb = sum(s["rb"] for s in seg), sum(s["qb"] for s in seg)
    if Qa <= 0 or Qb <= 0:
        raise DrillError(f"{volume.replace('_', ' ')} is zero in one of the periods, so there is no price to compare")

    pavg_a = Ra / Qa
    volume_effect = (Qb - Qa) * pavg_a
    mix_effect = price_effect = 0.0
    for s in seg:
        pa_i = s["ra"] / s["qa"] if s["qa"] else None
        pb_i = s["rb"] / s["qb"] if s["qb"] else None
        # a member new in B has no old price: all of it is mix; a member gone
        # in B contributes no price change. Either way the identity holds.
        pa_i = pa_i if pa_i is not None else (pb_i or 0.0)
        pb_i = pb_i if pb_i is not None else pa_i
        s_a, s_b = s["qa"] / Qa, s["qb"] / Qb
        s["mix"] = Qb * (s_b - s_a) * pa_i
        s["price"] = s["qb"] * (pb_i - pa_i)
        s["volume"] = (Qb - Qa) * s_a * pa_i
        s["price_a"], s["price_b"] = (s["ra"] / s["qa"] if s["qa"] else None), (s["rb"] / s["qb"] if s["qb"] else None)
        s["delta"] = s["rb"] - s["ra"]
        mix_effect += s["mix"]
        price_effect += s["price"]
    delta = Rb - Ra
    unexplained = delta - (volume_effect + mix_effect + price_effect)
    if abs(unexplained) < 1e-6 * max(1.0, abs(delta)):
        unexplained = 0.0

    seg.sort(key=lambda s: abs(s["delta"]), reverse=True)
    subtype = sl.measures.get(measure)
    return {
        "measure": measure, "volume": volume, "dimension": dimension, "subtype": subtype,
        "volume_subtype": sl.measures.get(volume),
        "a": {"from": pa[0].isoformat(), "to": pa[1].isoformat(), "label": _label(*pa),
              "value": Ra, "volume": Qa, "avg_price": pavg_a},
        "b": {"from": pb[0].isoformat(), "to": pb[1].isoformat(), "label": _label(*pb),
              "value": Rb, "volume": Qb, "avg_price": Rb / Qb},
        "delta": delta,
        "effects": {"volume": volume_effect, "mix": mix_effect, "price": price_effect,
                    "unexplained": unexplained},
        "like_for_like": per["like_for_like"],
        "segments": [{k: s[k] for k in ("name", "delta", "volume", "mix", "price", "qa", "qb", "price_a", "price_b")}
                     for s in seg[:max(1, min(int(limit), MAX_STEPS))]],
        "candidates": candidates,
        "volume_candidates": [m for m in sl.measures if m != measure],
    }
