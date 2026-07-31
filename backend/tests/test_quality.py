"""Percentage detection + data-quality profiling + cleaning actions."""

import csv
import io

import pandas as pd

from app.analytics.detect import detect_column
from app.analytics.quality import apply_cleaning, compute_quality
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# ---- percentage detection ----

def test_percentage_detected_by_name():
    s = pd.Series([12, 45, 78, 33, 90, 21, 66])
    assert detect_column("conversion_rate", s).subtype == "percentage"
    assert detect_column("profit_margin", s).subtype == "percentage"


def test_percentage_detected_by_fractional_values():
    s = pd.Series([0.12, 0.45, 0.78, 0.33, 0.9, 0.21])
    assert detect_column("score", s).subtype == "percentage"


def test_currency_still_wins_for_revenue():
    s = pd.Series([1000, 2000, 3500, 4200, 900])
    assert detect_column("revenue", s).subtype == "currency"


# ---- quality profiling ----

def _seed(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    rows = [["date", "branch", "revenue"],
            ["2025-01-05", "Delhi", "1000"],
            ["2025-01-06", "Mumbai", ""],        # missing revenue
            ["2025-01-07", "", "1500"],          # missing branch
            ["2025-01-05", "Delhi", "1000"],     # duplicate of row 1
            ["2025-01-09", "Delhi", "99999"]]    # revenue outlier
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(rows))
    return res.dataset_id


def test_quality_reports_missing_duplicates_outliers(con):
    dsid = _seed(con)
    q = compute_quality(con, "ws_a", dsid)
    assert q["duplicate_rows"] == 1
    rev = next(c for c in q["columns"] if c["name"] == "revenue")
    branch = next(c for c in q["columns"] if c["name"] == "branch")
    assert rev["missing_count"] == 1
    assert branch["missing_count"] == 1
    assert rev.get("outlier_count", 0) >= 1
    # a drop-duplicates suggestion and fill suggestions exist
    ids = {s["id"] for s in q["suggestions"]}
    assert "drop_duplicates" in ids and "fill_revenue" in ids and "fill_branch" in ids


def test_clean_drop_duplicates(con):
    dsid = _seed(con)
    before = compute_quality(con, "ws_a", dsid)["row_count"]
    result = apply_cleaning(con, "ws_a", dsid, "drop_duplicates")
    assert result["removed"] == 1
    after = compute_quality(con, "ws_a", dsid)
    assert after["row_count"] == before - 1
    assert after["duplicate_rows"] == 0


def test_clean_fill_missing_median(con):
    dsid = _seed(con)
    result = apply_cleaning(con, "ws_a", dsid, "fill_median", column="revenue")
    assert result["filled"] == 1
    after = compute_quality(con, "ws_a", dsid)
    assert next(c for c in after["columns"] if c["name"] == "revenue")["missing_count"] == 0


def test_clean_rejects_unknown_column(con):
    import pytest
    from app.analytics.quality import QualityError
    dsid = _seed(con)
    with pytest.raises(QualityError):
        apply_cleaning(con, "ws_a", dsid, "fill_mean", column="password_hash")
