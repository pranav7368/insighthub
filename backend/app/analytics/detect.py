"""Auto-detect what each column of an uploaded structured file IS.

Deliberately plain heuristics, not an LLM guess: a dashboard chart cannot
show a citation the way a Q&A answer can, so column roles are decided by
inspecting the actual data (dtype, cardinality, name). Every detected role
is stored and shown to the admin, and can be overridden.

Roles: measure (number to chart) | dimension (category to group/filter) |
date (time axis) | ignored (IDs / free text / too-granular).
"""

import re
from dataclasses import dataclass

import pandas as pd

from ..core import config

BUSINESS_UNIT_HINTS = {
    "business_unit", "businessunit", "department", "dept", "division",
    "segment", "unit", "team", "product_line",
}
BRANCH_HINTS = {
    "branch", "location", "store", "outlet", "region", "city", "office",
    "site", "center", "centre",
}
MEASURE_NAME_HINTS = {
    "revenue", "sales", "profit", "cost", "expense", "amount", "price",
    "units", "unit", "qty", "quantity", "count", "total", "budget",
    "headcount", "margin", "churn", "score", "rating", "spend",
}
CURRENCY_HINTS = {"revenue", "sales", "profit", "cost", "expense", "amount", "price", "budget", "spend"}
PERCENT_HINTS = {"pct", "percent", "percentage", "rate", "ratio", "margin", "share", "growth"}
ID_NAME_HINTS = {"id", "uuid", "code", "key", "ref", "reference"}


@dataclass
class ColumnProfile:
    name: str
    role: str
    subtype: str | None
    distinct_count: int


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _matches_any(norm_name: str, hints: set[str]) -> bool:
    tokens = set(norm_name.split())
    return any(hint in norm_name or hint in tokens for hint in hints)


def _looks_like_id(norm_name: str, series: pd.Series) -> bool:
    if _matches_any(norm_name, ID_NAME_HINTS):
        return True
    # high cardinality is normal for a continuous numeric measure (revenue,
    # price); only the NAME gives away an ID for numeric columns
    if pd.api.types.is_numeric_dtype(series):
        return False
    n = len(series)
    return n > 20 and series.nunique(dropna=True) >= n * 0.98


def _try_parse_dates(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    # A column pandas already typed as numeric is a number, not a date.
    # Never coerce it via string parsing - otherwise small integers like
    # 1000/2025 get misread as years and a measure looks like a date.
    if pd.api.types.is_numeric_dtype(series):
        return False
    sample = series.dropna().astype(str).head(30)
    if sample.empty:
        return False
    try:
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return False
    return parsed.notna().mean() >= 0.8


def detect_column(name: str, series: pd.Series) -> ColumnProfile:
    norm_name = _norm(name)
    distinct = int(series.nunique(dropna=True))

    # Dates must be checked BEFORE the ID heuristic: a real date/timestamp
    # column is very often all-unique (one row per moment), and the
    # high-cardinality ID rule would otherwise swallow it and silently break
    # every time-series feature (trend, forecast, anomalies).
    if _try_parse_dates(series):
        return ColumnProfile(name, "date", None, distinct)
    if _looks_like_id(norm_name, series):
        return ColumnProfile(name, "ignored", None, distinct)
    if pd.api.types.is_numeric_dtype(series):
        # percentage takes priority (even at low cardinality): a name hint, an
        # explicit '%', or values that sit in a fractional 0..1 range (with
        # some spread, so a 0/1 flag isn't mistaken for a percentage)
        nums = pd.to_numeric(series, errors="coerce").dropna()
        fractional = len(nums) > 0 and nums.between(0, 1).mean() >= 0.98 and nums.nunique() > 2
        if _matches_any(norm_name, PERCENT_HINTS) or "%" in name or fractional:
            return ColumnProfile(name, "measure", "percentage", distinct)
        low_card = distinct <= config.MAX_NUMERIC_DIMENSION_CARDINALITY
        named_measure = _matches_any(norm_name, MEASURE_NAME_HINTS)
        if low_card and not named_measure:
            return ColumnProfile(name, "dimension", "generic", distinct)
        subtype = "currency" if _matches_any(norm_name, CURRENCY_HINTS) else "count"
        return ColumnProfile(name, "measure", subtype, distinct)
    if distinct > config.MAX_DIMENSION_CARDINALITY:
        return ColumnProfile(name, "ignored", None, distinct)
    if _matches_any(norm_name, BUSINESS_UNIT_HINTS):
        return ColumnProfile(name, "dimension", "business_unit", distinct)
    if _matches_any(norm_name, BRANCH_HINTS):
        return ColumnProfile(name, "dimension", "branch", distinct)
    return ColumnProfile(name, "dimension", "generic", distinct)


def detect_schema(df: pd.DataFrame) -> list[ColumnProfile]:
    return [detect_column(col, df[col]) for col in df.columns]
