"""The analytics intelligence layer: forecasting, anomaly detection, and
automated insights / recommendations.

Design principle (same as the rest of the product): NOTHING here is an LLM
guess. Every forecast, flag, and recommendation is computed deterministically
from the actual aggregated numbers, so it is reproducible and traceable. A
projection is always labelled as a projection and carries a confidence band;
an insight always cites the figures it is derived from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# --------------------------------------------------------- period math ---

def next_month(period: str) -> str:
    """'2025-12' -> '2026-01'."""
    year, month = (int(x) for x in period.split("-"))
    month += 1
    if month > 12:
        month, year = 1, year + 1
    return f"{year:04d}-{month:02d}"


def future_periods(last_period: str, horizon: int) -> list[str]:
    out, cur = [], last_period
    for _ in range(horizon):
        cur = next_month(cur)
        out.append(cur)
    return out


# ------------------------------------------------------- value format ----

def format_value(value, subtype: str | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    n = float(value)
    if subtype == "percentage":
        v = n * 100 if abs(n) <= 1 else n
        return f"{v:.1f}%"
    if subtype == "currency":
        if abs(n) >= 1e7:
            return f"₹{n / 1e7:.2f} Cr"
        if abs(n) >= 1e5:
            return f"₹{n / 1e5:.2f} L"
        return f"₹{n:,.0f}"
    if abs(n) >= 1e5:
        return f"{n:,.0f}"
    return f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().title()


# --------------------------------------------------------- core stats ----

def _linear_fit(values: np.ndarray):
    """Least-squares line over t = 0..n-1. Returns (intercept, slope,
    fitted, residual_std)."""
    n = len(values)
    t = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(t, values, 1)
    fitted = intercept + slope * t
    resid = values - fitted
    resid_std = float(np.std(resid, ddof=1)) if n > 2 else float(np.std(resid))
    return float(intercept), float(slope), fitted, resid_std


def _seasonal_additive(values: np.ndarray, fitted: np.ndarray, period: int = 12) -> np.ndarray:
    """Average detrended deviation per season slot (month-of-year)."""
    resid = values - fitted
    seasonal = np.zeros(period)
    for s in range(period):
        idx = np.arange(s, len(values), period)
        if len(idx):
            seasonal[s] = resid[idx].mean()
    seasonal -= seasonal.mean()  # keep it zero-sum so it doesn't shift the level
    return seasonal


@dataclass
class Forecast:
    method: str
    history: list[dict]
    forecast: list[dict]

    def as_dict(self):
        return {"method": self.method, "history": self.history, "forecast": self.forecast}


def forecast_series(periods: list[str], values: list[float], subtype: str | None,
                    horizon: int = 3, non_negative: bool = True) -> Forecast:
    """Project a monthly series forward. Linear trend, plus an additive
    monthly-seasonal component when >= 2 full years are available. 95%
    prediction band from residual spread, widening with horizon."""
    y = np.asarray(values, dtype=float)
    n = len(y)
    history = [{"period": p, "value": float(v)} for p, v in zip(periods, values)]
    if n < 4:
        return Forecast(method="insufficient_history", history=history, forecast=[])

    intercept, slope, fitted, resid_std = _linear_fit(y)
    use_seasonal = n >= 24
    seasonal = _seasonal_additive(y, fitted, 12) if use_seasonal else None
    start_month = int(periods[-1].split("-")[1])  # month-of-year of last point

    fut_periods = future_periods(periods[-1], horizon)
    out = []
    for h, p in enumerate(fut_periods, start=1):
        t = n - 1 + h
        point = intercept + slope * t
        if seasonal is not None:
            point += seasonal[(start_month - 1 + h) % 12]
        # band widens with the square root of horizon (random-walk-like)
        band = 1.96 * resid_std * math.sqrt(h)
        lower, upper = point - band, point + band
        if non_negative:
            point, lower = max(point, 0.0), max(lower, 0.0)
        out.append({"period": p, "value": round(point, 2),
                    "lower": round(lower, 2), "upper": round(max(upper, 0.0), 2)})
    method = "linear+seasonal" if use_seasonal else "linear"
    return Forecast(method=method, history=history, forecast=out)


def moving_average(values: list[float], window: int = 3) -> list[float | None]:
    """Trailing simple moving average; None until the window fills."""
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(round(sum(values[i + 1 - window:i + 1]) / window, 2))
    return out


def growth_rates(series: list[dict]) -> dict:
    """Month-over-month, quarter-over-quarter and year-over-year growth from a
    monthly series ([{period, value}, ...])."""
    vals = [p["value"] for p in series]
    n = len(vals)

    def pct(old, new):
        return None if old in (0, None) else round((new - old) / abs(old) * 100, 1)

    out = {"mom": None, "qoq": None, "yoy": None}
    if n >= 2:
        out["mom"] = pct(vals[-2], vals[-1])
    if n >= 6:
        out["qoq"] = pct(sum(vals[-6:-3]), sum(vals[-3:]))  # last 3 mo vs prior 3 mo
    if n >= 13:
        out["yoy"] = pct(vals[-13], vals[-1])               # same month last year
    return out


def pareto_analysis(data: list[dict]) -> dict | None:
    """80/20 view of a breakdown (already sorted desc, with share_pct):
    cumulative share and how many categories reach ~80%."""
    if not data:
        return None
    cum, items, n80 = 0.0, [], None
    for i, d in enumerate(data):
        cum += d.get("share_pct") or 0
        items.append({"name": d["name"], "share_pct": d.get("share_pct"),
                      "cumulative_pct": round(cum, 1)})
        if n80 is None and cum >= 80:
            n80 = i + 1
    return {"items": items, "n_for_80": n80, "total_categories": len(data)}


def detect_anomalies(periods: list[str], values: list[float], z: float = 2.5) -> list[dict]:
    """Flag points whose detrended residual exceeds z standard deviations."""
    y = np.asarray(values, dtype=float)
    if len(y) < 5:
        return []
    _, _, fitted, resid_std = _linear_fit(y)
    # treat a numerically-negligible spread as "no variation" - otherwise a
    # perfectly straight line's ~1e-13 residuals get divided into huge
    # z-scores and produce phantom anomalies
    scale = float(np.mean(np.abs(y))) + 1.0
    if resid_std <= 1e-6 * scale:
        return []
    anomalies = []
    for i, (p, v) in enumerate(zip(periods, values)):
        deviation = (v - fitted[i]) / resid_std
        if abs(deviation) >= z:
            anomalies.append({
                "period": p, "value": float(v), "expected": round(float(fitted[i]), 2),
                "direction": "spike" if deviation > 0 else "dip",
                "severity": "critical" if abs(deviation) >= 3.5 else "warning",
            })
    return anomalies


# ------------------------------------------------- insights / advice -----

@dataclass
class Insight:
    severity: str        # good | warning | critical | info
    title: str
    detail: str
    category: str = "general"

    def as_dict(self):
        return self.__dict__.copy()


def _pct_change(old: float, new: float) -> float | None:
    if old in (0, None):
        return None
    return (new - old) / abs(old) * 100.0


def build_insights(
    *,
    measures: list[dict],
    series_by_measure: dict[str, list[dict]],   # measure -> [{period, value}]
    breakdowns: dict[str, dict],                # dim -> {subtype, data:[{name,value,share_pct}]}
    forecasts: dict[str, dict],
    anomalies: dict[str, list[dict]],
    primary_measure: str | None,
    pareto: dict | None = None,
) -> list[Insight]:
    insights: list[Insight] = []
    sub = {m["name"]: m["subtype"] for m in measures}

    def fv(measure, value):
        return format_value(value, sub.get(measure))

    # ---- per primary-measure trend + momentum + forecast ----
    pm = primary_measure
    if pm and pm in series_by_measure and len(series_by_measure[pm]) >= 2:
        series = series_by_measure[pm]
        first, last = series[0]["value"], series[-1]["value"]
        change = _pct_change(first, last)
        label = _humanize(pm)
        if change is not None:
            if change >= 5:
                insights.append(Insight("good", f"{label} is trending up",
                    f"{label} rose {change:+.1f}% from {series[0]['period']} ({fv(pm, first)}) "
                    f"to {series[-1]['period']} ({fv(pm, last)}).", "trend"))
            elif change <= -5:
                insights.append(Insight("warning", f"{label} is trending down",
                    f"{label} fell {change:.1f}% from {series[0]['period']} ({fv(pm, first)}) "
                    f"to {series[-1]['period']} ({fv(pm, last)}).", "trend"))
            else:
                insights.append(Insight("info", f"{label} is broadly flat",
                    f"{label} moved {change:+.1f}% across the period — no strong trend.", "trend"))
        if len(series) >= 2:
            mom = _pct_change(series[-2]["value"], series[-1]["value"])
            if mom is not None and abs(mom) >= 8:
                sev = "good" if mom > 0 else "warning"
                insights.append(Insight(sev, f"Latest month {'jumped' if mom > 0 else 'dropped'} {abs(mom):.0f}%",
                    f"{label} went from {fv(pm, series[-2]['value'])} in {series[-2]['period']} "
                    f"to {fv(pm, series[-1]['value'])} in {series[-1]['period']} ({mom:+.1f}%).", "momentum"))
        fc = forecasts.get(pm, {}).get("forecast") or []
        if fc:
            nxt = fc[0]
            insights.append(Insight("info", f"Projected next month: {fv(pm, nxt['value'])}",
                f"Based on the trend, {label} is projected at {fv(pm, nxt['value'])} in {nxt['period']} "
                f"(range {fv(pm, nxt['lower'])}–{fv(pm, nxt['upper'])}). This is a model projection, not a guarantee.",
                "forecast"))

    # ---- concentration risk on the primary breakdown ----
    for dim, bd in breakdowns.items():
        data = bd.get("data") or []
        if len(data) >= 2 and data[0].get("share_pct") is not None:
            top = data[0]
            if top["share_pct"] >= 40:
                insights.append(Insight("warning", f"High concentration in {top['name']}",
                    f"{top['name']} alone accounts for {top['share_pct']:.0f}% of "
                    f"{_humanize(pm) if pm else 'the total'} across {_humanize(dim)} — a dependency risk.",
                    "concentration"))
            break  # only the first/primary dimension

    # ---- best & fastest-moving segment ----
    for dim, bd in breakdowns.items():
        data = bd.get("data") or []
        if data:
            best = data[0]
            insights.append(Insight("good", f"Top {_humanize(dim)}: {best['name']}",
                f"{best['name']} leads {_humanize(dim)} with {fv(pm, best['value'])}"
                + (f" ({best['share_pct']:.0f}% share)." if best.get('share_pct') is not None else "."),
                "leader"))
        break

    # ---- anomalies (one callout per period; prefer the primary measure) ----
    seen_periods: set[str] = set()
    ordered = sorted(anomalies.items(), key=lambda kv: (kv[0] != pm, kv[0]))
    for measure, items in ordered:
        for a in items:
            if a["period"] in seen_periods:
                continue
            seen_periods.add(a["period"])
            insights.append(Insight(a["severity"], f"Unusual {a['direction']} in {a['period']}",
                f"{_humanize(measure)} was {fv(measure, a['value'])} in {a['period']}, "
                f"vs an expected ~{fv(measure, a['expected'])}. Worth investigating.", "anomaly"))

    # ---- Pareto (80/20) ----
    if pareto and pareto.get("n_for_80") and pareto.get("total_categories", 0) > pareto["n_for_80"]:
        n80, total = pareto["n_for_80"], pareto["total_categories"]
        dim = _humanize(pareto.get("dimension", "categories"))
        insights.append(Insight("info", f"Pareto: {n80} of {total} {dim} drive ~80%",
            f"The top {n80} of {total} {dim.lower()} account for about 80% of "
            f"{_humanize(pm) if pm else 'the total'} — focus effort there.", "pareto"))

    # ---- margin insight when both revenue & profit exist ----
    names = {m["name"].lower(): m["name"] for m in measures}
    rev = next((names[k] for k in names if "revenue" in k or "sales" in k), None)
    prof = next((names[k] for k in names if "profit" in k), None)
    if rev and prof and rev in series_by_measure and prof in series_by_measure:
        rev_total = sum(p["value"] for p in series_by_measure[rev])
        prof_total = sum(p["value"] for p in series_by_measure[prof])
        if rev_total:
            margin = prof_total / rev_total * 100
            sev = "good" if margin >= 15 else "warning" if margin < 8 else "info"
            insights.append(Insight(sev, f"Overall margin: {margin:.1f}%",
                f"{_humanize(prof)} is {margin:.1f}% of {_humanize(rev)} "
                f"({fv(prof, prof_total)} on {fv(rev, rev_total)}).", "margin"))

    # rank: critical > warning > good > info, keep order within
    rank = {"critical": 0, "warning": 1, "good": 2, "info": 3}
    insights.sort(key=lambda i: rank.get(i.severity, 4))
    return insights
