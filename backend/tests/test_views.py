"""Saved dashboard views: CRUD, config validation, default, isolation."""

import csv
import io

import pytest

from app.analytics.engine import DatasetNotFound
from app.analytics.views import (
    ViewError, ViewNotFound, create_view, delete_view, list_views,
    set_default_view, update_view,
)
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SALES = [["date", "branch", "revenue"],
         ["2025-01-05", "Delhi", "1000"],
         ["2025-01-06", "Mumbai", "2000"]]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    return con, "ws_a", res.dataset_id


CFG = {"filters": {"branch": "Delhi"}, "date_from": "2025-01", "measure": "revenue",
       "hidden_sections": ["treemap", "pareto"]}


# ------------------------------------------------------- create + read ----

def test_create_and_list_roundtrip(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "Delhi Q1", CFG)
    assert v["name"] == "Delhi Q1"
    assert v["config"]["filters"] == {"branch": "Delhi"}
    assert v["config"]["hidden_sections"] == ["treemap", "pareto"]
    listed = list_views(con, ws, dsid)
    assert len(listed) == 1 and listed[0]["view_id"] == v["view_id"]


def test_create_requires_name(ds):
    con, ws, dsid = ds
    with pytest.raises(ViewError):
        create_view(con, ws, dsid, "   ", CFG)


def test_create_on_foreign_dataset_is_404(ds):
    con, _, dsid = ds
    # ws_b cannot attach a view to ws_a's dataset
    with pytest.raises(DatasetNotFound):
        create_view(con, "ws_b", dsid, "x", CFG)


# ------------------------------------------------------- validation -------

def test_unknown_section_rejected(ds):
    con, ws, dsid = ds
    with pytest.raises(ViewError):
        create_view(con, ws, dsid, "bad", {"hidden_sections": ["not_a_section"]})


def test_section_order_roundtrip(ds):
    con, ws, dsid = ds
    order = ["forecast", "kpis", "breakdowns"]
    v = create_view(con, ws, dsid, "arranged", {**CFG, "section_order": order})
    assert v["config"]["section_order"] == order


def test_section_order_defaults_to_empty(ds):
    """An old view saved before ordering existed still loads."""
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "legacy", {"measure": "revenue"})
    assert v["config"]["section_order"] == []


def test_section_order_rejects_unknown_keys(ds):
    con, ws, dsid = ds
    with pytest.raises(ViewError):
        create_view(con, ws, dsid, "bad order", {"section_order": ["kpis", "wat"]})


def test_section_order_is_deduped_keeping_first_position(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "dupes", {"section_order": ["kpis", "forecast", "kpis"]})
    assert v["config"]["section_order"] == ["kpis", "forecast"]


def test_oversized_config_rejected(ds):
    con, ws, dsid = ds
    huge = {"filters": {f"k{i}": "v" * 100 for i in range(200)}}
    with pytest.raises(ViewError):
        create_view(con, ws, dsid, "big", huge)


def test_filter_values_coerced_to_strings(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "coerce", {"filters": {"branch": 5}})
    assert v["config"]["filters"] == {"branch": "5"}


# ---------------------------------------------------------- default -------

def test_only_one_default_per_dataset(ds):
    con, ws, dsid = ds
    a = create_view(con, ws, dsid, "A", CFG, make_default=True)
    b = create_view(con, ws, dsid, "B", CFG)
    set_default_view(con, ws, b["view_id"])
    defaults = [v for v in list_views(con, ws, dsid) if v["is_default"]]
    assert len(defaults) == 1 and defaults[0]["view_id"] == b["view_id"]
    assert not next(v for v in list_views(con, ws, dsid) if v["view_id"] == a["view_id"])["is_default"]


# ----------------------------------------------------------- update -------

def test_update_name_and_config(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "old", CFG)
    upd = update_view(con, ws, v["view_id"], name="new", config={"measure": "revenue"})
    assert upd["name"] == "new"
    assert upd["config"]["measure"] == "revenue"
    assert upd["config"]["filters"] == {}          # replaced, not merged


def test_update_missing_view_raises(ds):
    con, ws, _ = ds
    with pytest.raises(ViewNotFound):
        update_view(con, ws, "view_nope", name="x")


# ---------------------------------------------------------- delete --------

def test_delete_view(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "temp", CFG)
    assert delete_view(con, ws, v["view_id"]) == 1
    assert list_views(con, ws, dsid) == []


# --------------------------------------------------------- isolation ------

def test_views_are_workspace_scoped(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "A-only", CFG)
    # ws_b sees nothing and cannot edit/delete ws_a's view
    assert list_views(con, "ws_b", dsid) == []
    with pytest.raises(ViewNotFound):
        update_view(con, "ws_b", v["view_id"], name="hijack")
    assert delete_view(con, "ws_b", v["view_id"]) == 0
