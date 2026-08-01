"""Correlation matrix + scatter (points, r, regression), all from real rows."""

import csv
import io

import pytest

from app.analytics.correlation import compute_scatter
from app.analytics.engine import compute_dashboard
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    # units_sold perfectly correlated with revenue (revenue = 10*units);
    # cost negatively related
    rows = [["date", "branch", "revenue", "units_sold", "cost"]]
    for i in range(1, 21):
        rows.append([f"2025-{(i % 12) + 1:02d}-05", "Delhi", str(1000 * i), str(100 * i), str(20000 - 500 * i)])
    res = ingest_upload(con, "ws_a", "s.csv", _csv(rows))
    return con, "ws_a", res.dataset_id


def test_dashboard_includes_correlation_matrix(ds):
    con, ws, dsid = ds
    dash = compute_dashboard(con, ws, dsid)
    corr = dash["correlations"]
    assert corr is not None
    assert set(corr["measures"]) == {"revenue", "units_sold", "cost"}
    # revenue vs units_sold is a perfect positive correlation
    i = corr["measures"].index("revenue")
    j = corr["measures"].index("units_sold")
    assert corr["matrix"][i][j] == 1.0
    # strongest pair is revenue/units_sold (|r| = 1)
    assert abs(corr["strongest"]["r"]) == 1.0


def test_dashboard_includes_scatter_for_strongest_pair(ds):
    con, ws, dsid = ds
    dash = compute_dashboard(con, ws, dsid)
    sc = dash["scatter"]
    assert sc is not None
    assert {sc["x"], sc["y"]} == {"revenue", "units_sold"}
    assert abs(sc["r"]) == 1.0
    assert len(sc["points"]) == 20
    assert sc["line"] and len(sc["line"]) == 2  # regression endpoints


def test_compute_scatter_arbitrary_pair(ds):
    con, ws, dsid = ds
    sc = compute_scatter(con, ws, dsid, "revenue", "cost")
    assert sc["r"] < 0  # revenue up, cost down -> negative correlation
    assert sc["subtype_x"] == "currency"


def test_compute_scatter_rejects_non_measure(ds):
    con, ws, dsid = ds
    with pytest.raises(ValueError):
        compute_scatter(con, ws, dsid, "revenue", "branch")  # branch is a dimension


def test_compute_scatter_rejects_unknown_column(ds):
    con, ws, dsid = ds
    with pytest.raises(ValueError):
        compute_scatter(con, ws, dsid, "revenue", "password_hash")


def test_treemap_builds_two_level_hierarchy(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "business_unit", "branch", "revenue"]]
    data = [("Retail", "Delhi", 100), ("Retail", "Mumbai", 60),
            ("Wholesale", "Delhi", 200), ("Wholesale", "Pune", 40)]
    for i, (bu, br, rev) in enumerate(data * 3):
        rows.append([f"2025-{(i % 12) + 1:02d}-05", bu, br, str(rev)])
    res = ingest_upload(con, "ws_a", "s.csv", _csv(rows))
    dash = compute_dashboard(con, "ws_a", res.dataset_id)
    tm = dash["treemap"]
    assert tm is not None
    # parent = business_unit (2 distinct) is coarser than branch (3 distinct)
    assert tm["parent_dim"] == "business_unit" and tm["child_dim"] == "branch"
    names = {p["name"] for p in tm["root"]}
    assert names == {"Retail", "Wholesale"}
    wholesale = next(p for p in tm["root"] if p["name"] == "Wholesale")
    assert any(c["name"] == "Delhi" for c in wholesale["children"])
