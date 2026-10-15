"""Model selection by backtest, the accuracy it reports, and the seasonal
phase — which the old seasonal model got wrong for any series not starting
in January."""

import math

import numpy as np
import pytest

from app.analytics.forecasting import ORDER, backtest, choose, forecast
from app.analytics.intelligence import forecast_series


def _months(start_year, start_month, n):
    out = []
    y, m = start_year, start_month
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _seasonal(n, start_month=1, trend=2.0, noise=0.0, seed=1):
    """A clear December peak and a July trough on a gentle trend."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        month = (start_month - 1 + i) % 12 + 1
        effect = {12: 80.0, 7: -40.0}.get(month, 0.0)
        out.append(500 + trend * i + effect + rng.normal(0, noise))
    return out


def test_a_seasonal_series_is_won_by_a_seasonal_model():
    y = np.array(_seasonal(36, noise=3))
    method, scores = choose(y)
    assert method in ("seasonal_naive", "linear_seasonal", "holt_winters")
    by = {s.method: s for s in scores}
    assert by[method].mae < by["linear"].mae / 3       # clearly better than a straight line


def test_a_straight_line_stays_a_straight_line():
    y = np.array([100 + 10 * i for i in range(14)], dtype=float)
    assert choose(y)[0] == "linear"


@pytest.mark.parametrize("start_month", [1, 3, 8])
def test_seasonal_phase_is_right_whatever_month_the_data_starts(start_month):
    """28 months of data; the next three months must put the peak on the
    December and the trough on the July that actually follow."""
    values = _seasonal(28, start_month=start_month)
    periods = _months(2023, start_month, 28)
    fc = forecast_series(periods, values, "count", horizon=12)
    by_month = {int(p["period"][5:]): p["value"] for p in fc.forecast}

    def neighbours(m):
        return (by_month[(m - 2) % 12 + 1] + by_month[m % 12 + 1]) / 2

    # a shifted phase would put the peak and the trough on the wrong months
    assert by_month[12] > neighbours(12) + 40, (fc.method, by_month)
    assert by_month[7] < neighbours(7) - 20, (fc.method, by_month)


def test_accuracy_is_the_real_backtest_error():
    y = np.array(_seasonal(30, noise=8, seed=4))
    out = forecast(y, 3)
    acc = out["accuracy"]
    winner = backtest(y, out["method"])
    assert acc["mae"] == round(winner.mae, 2)
    assert acc["tests"] == winner.count and acc["months"] == len(winner.errors[1])
    assert {c["method"] for c in acc["candidates"]} <= set(ORDER)
    # the band is the RMSE of the real one-step misses
    one_step = winner.errors[1]
    assert out["band_sd"] == pytest.approx(math.sqrt(sum(e * e for e in one_step) / len(one_step)))


def test_backtest_only_scores_months_that_happened():
    y = np.array(_seasonal(20, noise=2), dtype=float)
    s = backtest(y, "holt_damped")
    # origins are the last 8 positions (6 + 3 - 1); each predicts what is left of its 3 months
    assert len(s.errors[1]) == 8 and len(s.errors[3]) == 6


def test_forecasts_are_deterministic_and_carry_their_label():
    values = _seasonal(26, noise=5, seed=9)
    periods = _months(2024, 1, 26)
    a = forecast_series(periods, values, "count").as_dict()
    b = forecast_series(periods, values, "count").as_dict()
    assert a == b
    assert a["label"] and a["accuracy"]["mape"] is not None


def test_short_history_still_forecasts_without_claiming_accuracy():
    fc = forecast_series(_months(2025, 1, 5), [10, 12, 13, 15, 16], "count").as_dict()
    assert len(fc["forecast"]) == 3 and fc["accuracy"] is None
