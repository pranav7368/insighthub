"""#3 auto-calculated metrics: growth (MoM/QoQ/YoY), moving average, Pareto,
plus std-dev / growth / pareto surfacing in the dashboard."""

import csv
import io

from app.analytics.engine import compute_dashboard
from app.analytics.intelligence import growth_rates, moving_average, pareto_analysis
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# ---- pure math ----

def test_moving_average_trails_and_pads():
    assert moving_average([10, 20, 30, 40], window=3) == [None, None, 20.0, 30.0]


def test_growth_rates_mom_qoq_yoy():
    series = [{"period": f"2024-{m:02d}", "value": 100 + 10 * m} for m in range(1, 13)]
    series += [{"period": "2025-01", "value": 260}]  # 13th point
    g = growth_rates(series)
    assert g["mom"] == round((260 - 220) / 220 * 100, 1)
    assert g["yoy"] == round((260 - 110) / 110 * 100, 1)   # vs 2024-01 (110)
    assert g["qoq"] is not None


def test_growth_rates_short_series():
    g = growth_rates([{"period": "2025-01", "value": 5}])
    assert g == {"mom": None, "qoq": None, "yoy": None}


def test_pareto_finds_80_percent_cutoff():
    data = [{"name": "A", "share_pct": 50}, {"name": "B", "share_pct": 35},
            {"name": "C", "share_pct": 10}, {"name": "D", "share_pct": 5}]
    p = pareto_analysis(data)
    assert p["n_for_80"] == 2            # A+B = 85% >= 80
    assert p["total_categories"] == 4
    assert p["items"][1]["cumulative_pct"] == 85.0


# ---- dashboard surfacing ----

def test_dashboard_includes_growth_std_and_pareto(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    rows = [["date", "branch", "revenue"]]
    branches = ["Delhi"] * 6 + ["Mumbai"] * 3 + ["Pune"]  # skewed -> pareto
    for m in range(1, 14):  # 13 months for YoY
        for b in branches:
            rows.append([f"{2024 + (m - 1) // 12}-{((m - 1) % 12) + 1:02d}-05", b, str(1000 + 50 * m)])
    res = ingest_upload(con, "ws_a", "s.csv", _csv(rows))
    dash = compute_dashboard(con, "ws_a", res.dataset_id)

    assert "std" in dash["distributions"]["revenue"]
    g = dash["growth"]["revenue"]
    assert g["mom"] is not None and g["yoy"] is not None
    assert dash["pareto"] is not None and dash["pareto"]["dimension"] == "branch"
    assert dash["forecasts"]["revenue"]["moving_avg"][-1] is not None
    # a pareto insight is present
    assert any(i["category"] == "pareto" for i in dash["insights"])
