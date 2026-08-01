"""Incremental ingestion (monthly appends): every case + rollback + isolation."""

import csv
import io

import pytest

from app.analytics.engine import compute_dashboard, get_columns
from app.ingest.append import append_to_dataset, list_batches, rollback_batch
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


JAN = [["date", "branch", "revenue"],
       ["2025-01-05", "Delhi", "1000"],
       ["2025-01-06", "Mumbai", "2000"]]
FEB = [["date", "branch", "revenue"],
       ["2025-02-05", "Delhi", "1500"],
       ["2025-02-06", "Mumbai", "2500"]]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    res = ingest_upload(con, "ws_a", "jan.csv", _csv(JAN))
    return con, "ws_a", res.dataset_id


def _rowcount(con, ws, dsid):
    return compute_dashboard(con, ws, dsid)["row_count_filtered"]


# ---- happy path: next month extends the dataset ----

def test_append_next_month(ds):
    con, ws, dsid = ds
    r = append_to_dataset(con, ws, dsid, "feb.csv", _csv(FEB))
    assert r["rows_added"] == 2 and r["skipped_duplicates"] == 0
    assert _rowcount(con, ws, dsid) == 4
    # the trend now spans two months
    assert len(compute_dashboard(con, ws, dsid)["trend"]) == 2


# ---- idempotent: re-uploading the same file adds nothing ----

def test_reupload_same_file_is_idempotent(ds):
    con, ws, dsid = ds
    r = append_to_dataset(con, ws, dsid, "jan.csv", _csv(JAN))
    assert r["rows_added"] == 0 and r["skipped_duplicates"] == 2
    assert _rowcount(con, ws, dsid) == 2


# ---- schema reconcile ----

def test_append_new_column_is_added(ds):
    con, ws, dsid = ds
    withcost = [["date", "branch", "revenue", "cost"],
                ["2025-02-05", "Delhi", "1500", "900"]]
    r = append_to_dataset(con, ws, dsid, "feb.csv", _csv(withcost))
    assert "cost" in r["new_columns"] and r["rows_added"] == 1
    assert "cost" in {c.name for c in get_columns(con, ws, dsid)}


def test_append_missing_column_blank(ds):
    con, ws, dsid = ds
    nobranch = [["date", "revenue"], ["2025-02-05", "1500"]]
    r = append_to_dataset(con, ws, dsid, "feb.csv", _csv(nobranch))
    assert "branch" in r["missing_columns"] and r["rows_added"] == 1


def test_append_rejects_unrelated_file(ds):
    con, ws, dsid = ds
    with pytest.raises(ValueError, match="shares no columns"):
        append_to_dataset(con, ws, dsid, "other.csv", _csv([["employee", "salary"], ["x", "5"]]))


# ---- replace period (corrections) ----

def test_replace_period_no_double_count(ds):
    con, ws, dsid = ds
    corrected = [["date", "branch", "revenue"],
                 ["2025-01-05", "Delhi", "9999"],
                 ["2025-01-06", "Mumbai", "8888"]]
    r = append_to_dataset(con, ws, dsid, "jan_fixed.csv", _csv(corrected), mode="replace_period")
    assert r["mode"] == "replace_period" and r["rows_removed"] == 2 and r["rows_added"] == 2
    assert _rowcount(con, ws, dsid) == 2                      # replaced, not doubled
    total = next(k for k in compute_dashboard(con, ws, dsid)["kpis"] if k["column"] == "revenue")["total"]
    assert total == 9999 + 8888                              # new values, old gone


# ---- rollback ----

def test_rollback_append(ds):
    con, ws, dsid = ds
    r = append_to_dataset(con, ws, dsid, "feb.csv", _csv(FEB))
    assert _rowcount(con, ws, dsid) == 4
    back = rollback_batch(con, ws, dsid, r["batch_id"])
    assert back["rows_deleted"] == 2 and _rowcount(con, ws, dsid) == 2


def test_rollback_replace_restores_original(ds):
    con, ws, dsid = ds
    before_total = next(k for k in compute_dashboard(con, ws, dsid)["kpis"] if k["column"] == "revenue")["total"]
    corrected = [["date", "branch", "revenue"], ["2025-01-05", "Delhi", "9999"], ["2025-01-06", "Mumbai", "8888"]]
    r = append_to_dataset(con, ws, dsid, "jan_fixed.csv", _csv(corrected), mode="replace_period")
    rollback_batch(con, ws, dsid, r["batch_id"])
    after_total = next(k for k in compute_dashboard(con, ws, dsid)["kpis"] if k["column"] == "revenue")["total"]
    assert after_total == before_total                        # original Jan values restored
    assert _rowcount(con, ws, dsid) == 2


def test_batches_are_listed(ds):
    con, ws, dsid = ds
    append_to_dataset(con, ws, dsid, "feb.csv", _csv(FEB))
    batches = list_batches(con, ws, dsid)
    assert len(batches) == 2                                   # initial + append
    assert batches[0]["mode"] == "append" and batches[-1]["mode"] == "initial"


# ---- tenant isolation ----

def test_cannot_append_to_another_workspace(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    a = ingest_upload(con, "ws_a", "jan.csv", _csv(JAN))
    from app.analytics.engine import DatasetNotFound
    with pytest.raises(DatasetNotFound):
        append_to_dataset(con, "ws_b", a.dataset_id, "feb.csv", _csv(FEB))


# ---- provenance column stays invisible ----

def test_batch_column_not_exposed(ds):
    con, ws, dsid = ds
    append_to_dataset(con, ws, dsid, "feb.csv", _csv(FEB))
    dash = compute_dashboard(con, ws, dsid)
    cols = {k["column"] for k in dash["kpis"]} | set(dash["breakdowns"].keys())
    assert not any(c.startswith("_ih") for c in cols)
