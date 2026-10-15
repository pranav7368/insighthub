"""Forecasting — several standard models, chosen by how well each predicted
this series' own past.

Candidates (each pure numpy, deterministic, cheap enough to refit per request):

  linear           least-squares trend
  seasonal_naive   same month last year (needs a year of history)
  holt_damped      Holt's exponential smoothing with a damped trend
  linear_seasonal  trend + additive month-of-year effect (needs two years)
  holt_winters     additive Holt-Winters (needs two years)

Selection is a rolling-origin backtest: from each of the last few months,
every model is refit on the data before it and asked to predict the next
1-3 months, which have actually happened. The model with the lowest mean
absolute error wins; a simpler model wins ties, so a clean straight line
stays a straight line. The winning model's backtest error is returned with
the forecast — "typically within ±4% over the last 6 months" — so the
projection says how far it can be trusted, and the prediction band is built
from those real errors rather than from an assumption.

Grid-searched smoothing parameters instead of an optimiser: a few hundred
fits of a 3-line recursion on at most a few dozen points, with no new
dependency and identical results on every machine.
"""

import math
from dataclasses import dataclass, field

import numpy as np

PERIOD = 12
MAX_ORIGINS = 6          # backtest from at most the last 6 months
EVAL_HORIZON = 3
MIN_EVALUATIONS = 3      # a model scored on fewer tests than this is not trusted
ORDER = ("linear", "seasonal_naive", "holt_damped", "linear_seasonal", "holt_winters")   # simplest first
MIN_TRAIN = {"linear": 4, "seasonal_naive": PERIOD, "holt_damped": 4,
             "linear_seasonal": 2 * PERIOD, "holt_winters": 2 * PERIOD}
LABELS = {"linear": "linear trend", "seasonal_naive": "same month last year",
          "holt_damped": "exponential smoothing (damped trend)",
          "linear_seasonal": "trend + seasonality", "holt_winters": "Holt-Winters (seasonal smoothing)"}

_ALPHAS = (0.1, 0.3, 0.5, 0.7, 0.9)
_BETAS = (0.05, 0.15, 0.3)
_PHIS = (0.8, 0.9, 0.98)
_GAMMAS = (0.05, 0.2, 0.4)


# ------------------------------------------------------------- models ---

def _linear(y: np.ndarray, h: int) -> np.ndarray:
    t = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(t, y, 1)
    return intercept + slope * (len(y) - 1 + np.arange(1, h + 1))


def _seasonal_naive(y: np.ndarray, h: int) -> np.ndarray:
    n = len(y)
    return np.array([y[n - PERIOD + ((i - 1) % PERIOD)] for i in range(1, h + 1)], dtype=float)


def _linear_seasonal(y: np.ndarray, h: int) -> np.ndarray:
    """Trend plus the average detrended deviation of each position in the
    year. Slots are indexed by position from the start of the series, for the
    fit and the projection alike — so the phase is right whichever month the
    data begins in."""
    n = len(y)
    t = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(t, y, 1)
    resid = y - (intercept + slope * t)
    seasonal = np.array([resid[s::PERIOD].mean() for s in range(PERIOD)])
    seasonal -= seasonal.mean()
    future = n - 1 + np.arange(1, h + 1)
    return intercept + slope * future + seasonal[future % PERIOD]


def _holt_path(y, alpha, beta, phi):
    level, trend = y[0], y[1] - y[0]
    sse = 0.0
    for v in y[1:]:
        pred = level + phi * trend
        sse += (v - pred) ** 2
        new_level = alpha * v + (1 - alpha) * pred
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return sse, level, trend


def _holt_damped(y: np.ndarray, h: int) -> np.ndarray:
    best = None
    for a in _ALPHAS:
        for b in _BETAS:
            for p in _PHIS:
                sse, level, trend = _holt_path(y, a, b, p)
                if best is None or sse < best[0]:
                    best = (sse, level, trend, p)
    _, level, trend, phi = best
    damp = np.cumsum([phi ** i for i in range(1, h + 1)])
    return level + damp * trend


def _hw_path(y, alpha, beta, gamma, m=PERIOD):
    level = y[:m].mean()
    trend = (y[m:2 * m].mean() - y[:m].mean()) / m
    season = list(y[:m] - level)
    sse = 0.0
    for i in range(m, len(y)):
        s = season[i - m]
        pred = level + trend + s
        sse += (y[i] - pred) ** 2
        new_level = alpha * (y[i] - s) + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        season.append(gamma * (y[i] - new_level) + (1 - gamma) * s)
        level = new_level
    return sse, level, trend, season


def _holt_winters(y: np.ndarray, h: int) -> np.ndarray:
    best = None
    for a in _ALPHAS[1::2]:
        for b in _BETAS:
            for g in _GAMMAS:
                fit = _hw_path(y, a, b, g)
                if best is None or fit[0] < best[0]:
                    best = fit
    _, level, trend, season = best
    n = len(y)
    return np.array([level + i * trend + season[n - PERIOD + ((i - 1) % PERIOD)]
                     for i in range(1, h + 1)], dtype=float)


MODELS = {"linear": _linear, "seasonal_naive": _seasonal_naive, "holt_damped": _holt_damped,
          "linear_seasonal": _linear_seasonal, "holt_winters": _holt_winters}


# ------------------------------------------------------------ backtest ---

@dataclass
class Score:
    method: str
    errors: dict = field(default_factory=dict)        # horizon -> [actual - predicted]
    pct: list = field(default_factory=list)           # |error| / |actual|, where actual != 0

    @property
    def count(self):
        return sum(len(v) for v in self.errors.values())

    @property
    def mae(self):
        all_e = [abs(e) for v in self.errors.values() for e in v]
        return sum(all_e) / len(all_e) if all_e else math.inf

    @property
    def mape(self):
        return (sum(self.pct) / len(self.pct) * 100.0) if self.pct else None


def backtest(y: np.ndarray, method: str) -> Score:
    score = Score(method)
    n = len(y)
    first = max(MIN_TRAIN[method], n - MAX_ORIGINS - EVAL_HORIZON + 1)
    for origin in range(first, n):
        steps = min(EVAL_HORIZON, n - origin)
        pred = MODELS[method](y[:origin], steps)
        for h in range(1, steps + 1):
            actual = y[origin + h - 1]
            err = float(actual - pred[h - 1])
            score.errors.setdefault(h, []).append(err)
            if actual != 0:
                score.pct.append(abs(err) / abs(actual))
    return score


def choose(y: np.ndarray) -> tuple[str, list[Score]]:
    scores = [backtest(y, m) for m in ORDER if len(y) > MIN_TRAIN[m]]
    trusted = [s for s in scores if s.count >= MIN_EVALUATIONS]
    if not trusted:
        return "linear", scores
    best = trusted[0]
    for s in trusted[1:]:
        # a more complex model has to be clearly better, not better by noise
        if s.mae < best.mae * 0.97:
            best = s
    return best.method, scores


def forecast(y: np.ndarray, horizon: int) -> dict:
    """{method, points, band_sd, accuracy} for a series of >= 4 points."""
    method, scores = choose(y)
    points = MODELS[method](y, horizon)
    chosen = next((s for s in scores if s.method == method), None)
    one_step = chosen.errors.get(1, []) if chosen else []
    if len(one_step) >= MIN_EVALUATIONS:
        sd = math.sqrt(sum(e * e for e in one_step) / len(one_step))      # RMSE of real one-step misses
    else:
        # too little history to have been tested: fall back to the spread
        # of the series around its own trend line
        t = np.arange(len(y), dtype=float)
        sd = float(np.std(y - np.polyval(np.polyfit(t, y, 1), t), ddof=1))
    accuracy = None
    if chosen and chosen.count >= MIN_EVALUATIONS:
        accuracy = {
            "mape": round(chosen.mape, 1) if chosen.mape is not None else None,
            "mae": round(chosen.mae, 2),
            "tests": chosen.count,
            "months": len(chosen.errors.get(1, [])),
            "candidates": [{"method": s.method, "label": LABELS[s.method], "mae": round(s.mae, 2),
                            "mape": round(s.mape, 1) if s.mape is not None else None, "tests": s.count}
                           for s in scores if s.count >= MIN_EVALUATIONS],
        }
    return {"method": method, "label": LABELS[method], "points": points, "band_sd": sd, "accuracy": accuracy}
