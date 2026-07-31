"""The intelligence layer: forecasting, anomaly detection, auto-insights,
plus the KPI period-over-period deltas the engine now returns."""

import csv
import io

from app.analytics.engine import compute_dashboard
from app.analytics.intelligence import (
    build_insights, detect_anomalies, forecast_series, next_month,
)
from app.ingest.pipeline import ingest_upload


# ---- period math ----

def test_next_month_rolls_over_year():
    assert next_month("2025-11") == "2025-12"
    assert next_month("2025-12") == "2026-01"


# ---- forecasting ----

def test_forecast_projects_upward_trend():
    periods = [f"2025-{m:02d}" for m in range(1, 13)]
    values = [100 + 10 * i for i in range(12)]  # strictly increasing
    fc = forecast_series(periods, values, "count", horizon=3)
    assert fc.method == "linear"
    assert len(fc.forecast) == 3
    assert fc.forecast[0]["period"] == "2026-01"
    # next value continues upward and sits within its band
    assert fc.forecast[0]["value"] > values[-1]
    assert fc.forecast[0]["lower"] <= fc.forecast[0]["value"] <= fc.forecast[0]["upper"]


def test_forecast_bands_widen_with_horizon():
    periods = [f"2025-{m:02d}" for m in range(1, 13)]
    values = [100 + 5 * i + (7 if i % 2 else -7) for i in range(12)]  # noisy
    fc = forecast_series(periods, values, "count", horizon=3)
    w1 = fc.forecast[0]["upper"] - fc.forecast[0]["lower"]
    w3 = fc.forecast[2]["upper"] - fc.forecast[2]["lower"]
    assert w3 > w1


def test_forecast_insufficient_history():
    fc = forecast_series(["2025-01", "2025-02"], [10, 20], "count")
    assert fc.method == "insufficient_history"
    assert fc.forecast == []


def test_forecast_non_negative_floor():
    periods = [f"2025-{m:02d}" for m in range(1, 13)]
    values = [200 - 18 * i for i in range(12)]  # declining toward/below zero
    fc = forecast_series(periods, values, "currency", horizon=6, non_negative=True)
    assert all(p["lower"] >= 0 and p["value"] >= 0 for p in fc.forecast)


# ---- anomaly detection ----

def test_detects_planted_spike():
    periods = [f"2025-{m:02d}" for m in range(1, 13)]
    values = [100 + 3 * i for i in range(12)]
    values[6] = 900  # obvious spike
    found = detect_anomalies(periods, values)
    assert any(a["period"] == "2025-07" and a["direction"] == "spike" for a in found)


def test_clean_series_has_no_anomalies():
    periods = [f"2025-{m:02d}" for m in range(1, 13)]
    values = [100 + 2 * i for i in range(12)]  # smooth line
    assert detect_anomalies(periods, values) == []


# ---- insights ----

def test_insights_flag_uptrend_and_concentration():
    series = {"revenue": [{"period": f"2025-{m:02d}", "value": 100 + 20 * m} for m in range(1, 13)]}
    breakdowns = {"branch": {"subtype": "branch", "data": [
        {"name": "Delhi", "value": 8000, "share_pct": 62.0},
        {"name": "Mumbai", "value": 3000, "share_pct": 23.0},
    ]}}
    insights = build_insights(
        measures=[{"name": "revenue", "subtype": "currency"}],
        series_by_measure=series, breakdowns=breakdowns,
        forecasts={}, anomalies={}, primary_measure="revenue",
    )
    titles = " ".join(i.title.lower() for i in insights)
    assert "trending up" in titles
    assert any(i.category == "concentration" for i in insights)


# ---- KPI deltas end to end ----

def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def test_all_unique_date_column_is_still_detected_as_date():
    # regression: a timestamp column where every value is unique must not be
    # swallowed by the ID heuristic (which would break all time-series features)
    import pandas as pd
    from app.analytics.detect import detect_column
    dates = pd.Series([f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}" for i in range(60)])
    assert dates.nunique() == len(dates)  # all unique
    assert detect_column("date", dates).role == "date"


def test_date_bounds_normalizes_month_and_is_end_exclusive():
    from app.analytics.engine import _date_bounds
    f, t = _date_bounds("2025-07", "2025-12")
    assert f == "2025-07-01 00:00:00"
    assert t == "2026-01-01 00:00:00"  # exclusive: includes all of December
    f2, t2 = _date_bounds("2025-02-15", None)
    assert f2 == "2025-02-15 00:00:00" and t2 is None


def test_dashboard_month_range_filter_works(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    rows = [["date", "branch", "revenue"]]
    for m in range(1, 13):
        rows.append([f"2025-{m:02d}-10", "Delhi", "1000"])
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(rows))
    # a YYYY-MM range must not raise and must filter correctly (Jul..Dec = 6 rows)
    dash = compute_dashboard(con, "ws_a", res.dataset_id, date_from="2025-07", date_to="2025-12")
    assert dash["row_count_filtered"] == 6


def test_dashboard_returns_kpi_delta_and_sparkline(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    rows = [["date", "branch", "revenue"]]
    for m in range(1, 13):
        rows.append([f"2025-{m:02d}-10", "Delhi", str(1000 + 100 * m)])
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(rows))
    dash = compute_dashboard(con, "ws_a", res.dataset_id)

    kpi = next(k for k in dash["kpis"] if k["column"] == "revenue")
    assert kpi["current_period"] == 2200  # month 12
    assert kpi["previous_period"] == 2100  # month 11
    assert kpi["delta_pct"] == round(100 / 2100 * 100, 1)
    assert len(kpi["sparkline"]) == 12
    assert "forecasts" in dash and "revenue" in dash["forecasts"]
    assert dash["data_profile"]["completeness_pct"] == 100.0
    assert len(dash["insights"]) >= 1
