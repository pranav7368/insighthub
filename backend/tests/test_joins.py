"""Multi-table joins: materialize, key suggestion, join types, collisions, scope."""

import csv
import io

import pytest

from app.analytics.engine import DatasetNotFound, compute_dashboard, get_columns
from app.analytics.joins import (
    JoinError, RelationNotFound, create_join, delete_relation, list_relations,
    rebuild_join, suggest_join_keys,
)
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


ORDERS = [["order_id", "customer_id", "amount"],
          ["o1", "c1", "100"], ["o2", "c2", "200"], ["o3", "c1", "300"],
          ["o4", "c9", "50"]]                       # c9 has no customer row
CUSTOMERS = [["customer_id", "region"],
             ["c1", "North"], ["c2", "South"]]


@pytest.fixture()
def two(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    o = ingest_upload(con, "ws_a", "orders.csv", _csv(ORDERS)).dataset_id
    c = ingest_upload(con, "ws_a", "customers.csv", _csv(CUSTOMERS)).dataset_id
    return con, "ws_a", o, c


# ------------------------------------------------------ suggest ------------

def test_suggest_finds_common_key(two):
    con, ws, o, c = two
    s = suggest_join_keys(con, ws, o, c)
    assert s["common"] == ["customer_id"]
    assert s["suggested"] == {"left_key": "customer_id", "right_key": "customer_id"}


# ------------------------------------------------------ create -------------

def test_left_join_keeps_all_left_rows(two):
    con, ws, o, c = two
    res = create_join(con, ws, o, c, "customer_id", "customer_id", "left")
    # 4 orders kept; region present for c1/c2, null for c9
    assert res["row_count"] == 4
    cols = {col.name for col in get_columns(con, ws, res["dataset_id"])}
    assert "region" in cols and "amount" in cols and "order_id" in cols
    # the joined dataset drives a real dashboard
    dash = compute_dashboard(con, ws, res["dataset_id"])
    amt = next(k for k in dash["kpis"] if k["column"] == "amount")
    assert amt["total"] == 650


def test_inner_join_drops_unmatched(two):
    con, ws, o, c = two
    res = create_join(con, ws, o, c, "customer_id", "customer_id", "inner")
    assert res["row_count"] == 3          # c9 order dropped


def test_column_collision_is_aliased(con):
    # both tables have a non-key column named "value"
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    left = ingest_upload(con, "ws_a", "l.csv", _csv([["k", "value"], ["1", "10"]])).dataset_id
    right = ingest_upload(con, "ws_a", "r.csv", _csv([["k", "value"], ["1", "99"]])).dataset_id
    res = create_join(con, "ws_a", left, right, "k", "k", "left")
    cols = {c.name for c in get_columns(con, "ws_a", res["dataset_id"])}
    assert "value" in cols                       # left's value
    assert any(c.endswith("_value") for c in cols)  # right's value, disambiguated


# ------------------------------------------------------ validation --------

def test_bad_key_rejected(two):
    con, ws, o, c = two
    with pytest.raises(JoinError):
        create_join(con, ws, o, c, "nope", "customer_id", "left")


def test_no_match_inner_join_errors(two):
    con, ws, o, c = two
    with pytest.raises(JoinError):
        create_join(con, ws, o, c, "order_id", "region", "inner")   # no overlap → empty


def test_foreign_dataset_is_404(two):
    con, _, o, c = two
    with pytest.raises(DatasetNotFound):
        create_join(con, "ws_b", o, c, "customer_id", "customer_id", "left")


# ------------------------------------------------ rebuild / delete ---------

def test_rebuild_reflects_new_source_rows(two):
    con, ws, o, c = two
    rel = create_join(con, ws, o, c, "customer_id", "customer_id", "inner")
    assert rel["row_count"] == 3
    # add a customer for c9, then a matching order already exists → rebuild picks it up
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('x', 'x')")  # noop keep ids distinct
    from app.ingest.append import append_to_dataset
    append_to_dataset(con, ws, c, "more.csv", _csv([["customer_id", "region"], ["c9", "West"]]))
    out = rebuild_join(con, ws, rel["relation_id"])
    assert out["row_count"] == 4                 # c9 order now matches


def test_delete_removes_dataset_and_relation(two):
    con, ws, o, c = two
    rel = create_join(con, ws, o, c, "customer_id", "customer_id", "left")
    assert delete_relation(con, ws, rel["relation_id"]) == 1
    assert list_relations(con, ws) == []
    with pytest.raises(DatasetNotFound):
        compute_dashboard(con, ws, rel["dataset_id"])   # joined dataset gone


def test_relations_are_workspace_scoped(two):
    con, ws, o, c = two
    rel = create_join(con, ws, o, c, "customer_id", "customer_id", "left")
    assert list_relations(con, "ws_b") == []
    assert delete_relation(con, "ws_b", rel["relation_id"]) == 0
    with pytest.raises(RelationNotFound):
        rebuild_join(con, "ws_b", rel["relation_id"])
