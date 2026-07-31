"""Certified metrics (semantic layer): compute, ratio, show-the-SQL, guard."""

import csv
import io

import pytest

from app.analytics.engine import DatasetNotFound
from app.analytics.semantic import (
    MetricError, compute_metric, create_metric, delete_metric, list_metrics,
)
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


DATA = [["date", "branch", "revenue", "profit"],
        ["2025-01-05", "Delhi", "1000", "200"],
        ["2025-01-06", "Mumbai", "2000", "500"],
        ["2025-02-05", "Delhi", "500", "100"]]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    res = ingest_upload(con, "ws_a", "Sales.csv", _csv(DATA))
    return con, "ws_a", res.dataset_id


# ---------------------------------------------------------- compute --------

def test_aggregate_metric(ds):
    con, ws, dsid = ds
    m = create_metric(con, ws, dsid, "Revenue", "aggregate", {"agg": "sum", "column": "revenue"}, "currency")
    value, sql = compute_metric(con, ws, dsid, m)
    assert value == 3500.0
    assert 'sum("revenue")' in sql and 'FROM "Sales"' in sql   # show-the-work, friendly name


def test_ratio_metric_as_percent(ds):
    con, ws, dsid = ds
    m = create_metric(con, ws, dsid, "Margin", "ratio",
                      {"numerator": {"agg": "sum", "column": "profit"},
                       "denominator": {"agg": "sum", "column": "revenue"}}, "percent")
    value, sql = compute_metric(con, ws, dsid, m)
    assert value == pytest.approx(800 / 3500 * 100)
    assert "* 100" in sql and "NULLIF" in sql


def test_count_and_count_distinct(ds):
    con, ws, dsid = ds
    total = create_metric(con, ws, dsid, "Rows", "aggregate", {"agg": "count"})
    assert compute_metric(con, ws, dsid, total)[0] == 3.0
    branches = create_metric(con, ws, dsid, "Branches", "aggregate",
                             {"agg": "count_distinct", "column": "branch"})
    assert compute_metric(con, ws, dsid, branches)[0] == 2.0


# --------------------------------------------------------- validation ------

def test_unknown_column_rejected(ds):
    con, ws, dsid = ds
    with pytest.raises(MetricError):
        create_metric(con, ws, dsid, "bad", "aggregate", {"agg": "sum", "column": "nope"})


def test_bad_aggregate_rejected(ds):
    con, ws, dsid = ds
    with pytest.raises(MetricError):
        create_metric(con, ws, dsid, "bad", "aggregate", {"agg": "drop", "column": "revenue"})


def test_ratio_needs_both_sides(ds):
    con, ws, dsid = ds
    with pytest.raises(MetricError):
        create_metric(con, ws, dsid, "bad", "ratio", {"numerator": {"agg": "sum", "column": "revenue"}})


def test_create_on_foreign_dataset_is_404(ds):
    con, _, dsid = ds
    with pytest.raises(DatasetNotFound):
        create_metric(con, "ws_b", dsid, "x", "aggregate", {"agg": "sum", "column": "revenue"})


# ------------------------------------------------- list + isolation --------

def test_list_includes_values_and_sql(ds):
    con, ws, dsid = ds
    create_metric(con, ws, dsid, "Revenue", "aggregate", {"agg": "sum", "column": "revenue"})
    listed = list_metrics(con, ws, dsid, with_values=True)
    assert len(listed) == 1
    assert listed[0]["value"] == 3500.0 and listed[0]["sql"] and listed[0]["error"] is None


def test_metrics_workspace_scoped(ds):
    con, ws, dsid = ds
    m = create_metric(con, ws, dsid, "Revenue", "aggregate", {"agg": "sum", "column": "revenue"})
    assert list_metrics(con, "ws_b", dsid, with_values=False) == []
    assert delete_metric(con, "ws_b", m["metric_id"]) == 0
    assert delete_metric(con, ws, m["metric_id"]) == 1
