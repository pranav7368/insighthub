"""Driver / root-cause analysis: decomposition math, primary driver, guards."""

import csv
import io

import pytest

from app.analytics.drivers import explain_change
from app.analytics.engine import DatasetNotFound
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# Jan total 300 (Delhi 100, Mumbai 200); Feb total 550 (Delhi 400, Mumbai 150)
# → delta +250, driven by Delhi (+300), offset by Mumbai (−50)
DATA = [["date", "branch", "revenue"],
        ["2025-01-05", "Delhi", "100"],
        ["2025-01-06", "Mumbai", "200"],
        ["2025-02-05", "Delhi", "400"],
        ["2025-02-06", "Mumbai", "150"]]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(DATA))
    return con, "ws_a", res.dataset_id


def test_decomposition_is_correct(ds):
    con, ws, dsid = ds
    r = explain_change(con, ws, dsid)
    assert r["available"] is True
    assert r["previous_total"] == 300 and r["current_total"] == 550
    assert r["delta"] == 250
    assert r["pct_change"] == pytest.approx(250 / 300 * 100)
    assert r["primary_dimension"] == "branch"

    drivers = {d["name"]: d for d in r["dimensions"]["branch"]["drivers"]}
    assert drivers["Delhi"]["delta"] == 300 and drivers["Mumbai"]["delta"] == -50
    assert drivers["Delhi"]["share"] == pytest.approx(300 / 250)


def test_summary_names_the_driver(ds):
    con, ws, dsid = ds
    r = explain_change(con, ws, dsid)
    assert "rose" in r["summary"] and "Delhi" in r["summary"]
    assert "Mumbai" in r["summary"]   # offset clause


def test_single_month_has_no_comparison(ds):
    con, ws, dsid = ds
    one = ingest_upload(con, ws, "one.csv",
                        _csv([["date", "branch", "revenue"], ["2025-01-01", "Delhi", "100"]])).dataset_id
    r = explain_change(con, ws, one)
    assert r["available"] is False and "two months" in r["reason"]


def test_no_date_column(ds):
    con, ws, _ = ds
    nod = ingest_upload(con, ws, "nod.csv",
                        _csv([["branch", "revenue"], ["Delhi", "100"], ["Mumbai", "200"]])).dataset_id
    r = explain_change(con, ws, nod)
    assert r["available"] is False and "date" in r["reason"]


def test_measure_selection_and_scope(ds):
    con, ws, dsid = ds
    # unknown measure falls back to the real one; cross-tenant is refused
    assert explain_change(con, ws, dsid, measure="ghost")["measure"] == "revenue"
    with pytest.raises(DatasetNotFound):
        explain_change(con, "ws_b", dsid)
