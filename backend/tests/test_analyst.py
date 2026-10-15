"""Phase-3 analyst features: targets, significance, the metric tree,
recommended actions, and questions asked from inside a drill."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.analytics.actions import recommend
from app.analytics.metrictree import explain_metric
from app.analytics.nlquery import QueryError, answer_data_question
from app.analytics.semantic import create_metric
from app.analytics.targets import TargetError, delete_target, evaluate, list_targets, set_target
from app.analytics.variance import explain_variance
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def _months(n_steady=10):
    """Jan..: North ~1000/month, South ~500/month with a little noise, then
    the last month North collapses to 400 — an unusual move."""
    rows = [["date", "region", "product", "revenue", "units", "profit"]]
    noise = [0, 20, -15, 10, -20, 15, -10, 5, -5, 25, -25, 0]
    for i in range(n_steady):
        m = f"2025-{i + 1:02d}"
        rows.append([f"{m}-05", "North", "Widget", str(1000 + noise[i]), "100", "200"])
        # half the noise, opposite sign: the total still wobbles (a flat total has no swing to measure)
        rows.append([f"{m}-15", "South", "Gadget", str(500 - noise[i] // 2), "10", "100"])
        rows.append([f"{m}-28", "East", "Widget", "100", "10", "20"])
    m = f"2025-{n_steady + 1:02d}"
    rows.append([f"{m}-05", "North", "Widget", "400", "50", "40"])
    rows.append([f"{m}-15", "South", "Gadget", "500", "10", "100"])
    rows.append([f"{m}-28", "East", "Widget", "100", "10", "20"])
    return rows


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(_months()))
    return con, "ws_a", res.dataset_id


# --------------------------------------------------------- significance ---

def test_an_unusual_move_is_flagged_and_a_normal_one_is_not(ds):
    con, ws, dsid = ds
    v = explain_variance(con, ws, dsid, measure="revenue")
    sig = v["significance"]
    assert v["delta"] == pytest.approx(1000 - 1613)   # Oct 1613 (1025 + 488 + 100) -> Nov 1000
    assert sig["level"] == "unusual" and sig["z"] < -2.5 and sig["history"] >= 5
    # South alone barely moves: normal
    south = explain_variance(con, ws, dsid, measure="revenue", filters={"region": "South"})
    assert south["significance"]["level"] == "normal"
    # year-ago has no series of comparable changes
    assert explain_variance(con, ws, dsid, measure="revenue", compare="year_ago")["significance"] is None


def test_too_little_history_says_nothing(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "region", "revenue"], ["2025-01-05", "N", "1"], ["2025-02-05", "N", "2"],
            ["2025-03-05", "N", "90"]]
    dsid = ingest_upload(con, "ws_a", "s.csv", _csv(rows)).dataset_id
    assert explain_variance(con, "ws_a", dsid, measure="revenue")["significance"] is None


# -------------------------------------------------------------- targets ---

def test_target_pace_and_status(ds):
    con, ws, dsid = ds
    # Nov ends on the 28th of 30 days: 1000 so far -> run rate 1000/28*30
    t = set_target(con, ws, dsid, measure="revenue", grain="month", period="2025-11", value=1000)
    e = evaluate(con, ws, dsid, t)
    assert e["actual"] == 1000 and e["status"] == "met" and e["current"] is True
    t = set_target(con, ws, dsid, measure="revenue", grain="month", period="2025-11", value=1100)
    e = evaluate(con, ws, dsid, t)
    assert e["projection"] == pytest.approx(1000 / 28 * 30)
    assert e["status"] == "at_risk"                      # 1071 / 1100 = 97%
    assert e["needed_per_day"] == pytest.approx(50)      # 100 short over 2 days
    # setting the same target again replaces it rather than stacking a second
    assert len(list_targets(con, ws, dsid)) == 1
    off = set_target(con, ws, dsid, measure="revenue", grain="month", period="2025-11", value=5000,
                     filters={"region": "North"})
    assert evaluate(con, ws, dsid, off)["status"] == "off_track"
    past = set_target(con, ws, dsid, measure="revenue", grain="quarter", period="2025-Q3", value=99999)
    assert evaluate(con, ws, dsid, past)["status"] == "missed"
    assert delete_target(con, ws, off["target_id"]) == 1
    assert delete_target(con, "ws_b", t["target_id"]) == 0          # tenant-scoped


@pytest.mark.parametrize("grain,period", [("month", "2025-13"), ("quarter", "2025-Q5"), ("week", "2025-11-05"),
                                          ("fortnight", "2025-11"), ("year", "25")])
def test_bad_periods_are_rejected(ds, grain, period):
    con, ws, dsid = ds
    with pytest.raises(TargetError):
        set_target(con, ws, dsid, measure="revenue", grain=grain, period=period, value=1)


def test_targets_reject_unknown_measures(ds):
    con, ws, dsid = ds
    with pytest.raises(TargetError):
        set_target(con, ws, dsid, measure="region", grain="month", period="2025-11", value=1)


# ----------------------------------------------------------- metric tree ---

def test_ratio_change_splits_exactly_into_its_parts(ds):
    con, ws, dsid = ds
    m = create_metric(con, ws, dsid, "Margin", "ratio",
                      {"numerator": {"agg": "sum", "column": "profit"},
                       "denominator": {"agg": "sum", "column": "revenue"}}, "percent")
    r = explain_metric(con, ws, m["metric_id"])
    assert r["a"]["value"] == pytest.approx(320 / 1613 * 100)
    assert r["b"]["value"] == pytest.approx(160 / 1000 * 100)
    assert r["numerator"]["effect"] + r["denominator"]["effect"] == pytest.approx(r["delta"])
    assert r["numerator"]["drill"] == {"measure": "profit", "agg": "sum"}
    assert "profit fell" in r["summary"]


def test_aggregate_metric_is_a_single_node(ds):
    con, ws, dsid = ds
    m = create_metric(con, ws, dsid, "Revenue", "aggregate", {"agg": "sum", "column": "revenue"}, "currency")
    r = explain_metric(con, ws, m["metric_id"])
    assert (r["a"]["value"], r["b"]["value"], r["delta"]) == (1613, 1000, -613)


# --------------------------------------------------------------- actions ---

def test_actions_are_grounded_and_carry_their_evidence(ds):
    con, ws, dsid = ds
    set_target(con, ws, dsid, measure="revenue", grain="month", period="2025-11", value=1500)
    r = recommend(con, ws, dsid, measure="revenue")
    kinds = [a["kind"] for a in r["actions"]]
    assert kinds[0] in ("unusual_move", "target", "declining_segment")
    assert {"unusual_move", "target", "declining_segment", "concentration"} <= set(kinds)
    north = next(a for a in r["actions"] if a["kind"] == "declining_segment")
    assert north["title"] == "Find out why North is falling"
    assert "1,025" in north["why"] and "400" in north["why"] and "(-61%)" in north["why"]
    assert north["evidence"]["filters"] == {"region": "North"} and north["evidence"]["tab"] == "change"
    # North sold 50 units for 400 (8 each, was 10): a price cut, named as a cost
    price = next(a for a in r["actions"] if a["kind"] == "price_erosion")
    assert "price changes alone cost" in price["why"] and "-" not in price["why"].split("cost")[1]
    target = next(a for a in r["actions"] if a["kind"] == "target")
    assert target["evidence"]["date_from"] == "2025-11-01"
    # severity is ordered
    order = [{"high": 0, "medium": 1, "low": 2}[a["severity"]] for a in r["actions"]]
    assert order == sorted(order)


@pytest.mark.parametrize("shares,flagged", [((40, 30, 30), False), ((55, 25, 20), True),
                                            ((41,) + (59 / 9,) * 9, True)])
def test_concentration_needs_more_than_an_even_share(con, shares, flagged):
    # 40% of three values is barely above an even third; 41% of ten is 4x it
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "region", "revenue"]]
    for i, share in enumerate(shares):
        rows += [[f"2025-01-{d:02d}", f"R{i}", str(share)] for d in (1, 2)]
    dsid = ingest_upload(con, "ws_a", "c.csv", _csv(rows)).dataset_id
    kinds = [a["kind"] for a in recommend(con, "ws_a", dsid, measure="revenue")["actions"]]
    assert ("concentration" in kinds) is flagged


def test_missing_values_are_called_out(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "region", "revenue"]] + [[f"2025-01-{d:02d}", "N", "" if d % 4 == 0 else "10"]
                                              for d in range(1, 21)]
    dsid = ingest_upload(con, "ws_a", "m.csv", _csv(rows)).dataset_id
    r = recommend(con, "ws_a", dsid, measure="revenue")
    miss = next(a for a in r["actions"] if a["kind"] == "missing_values")
    assert "5 of 20 rows (25%)" in miss["why"]


# ------------------------------------------------------- ask in context ---

def test_a_question_asked_inside_a_drill_stays_inside_it(ds):
    con, ws, dsid = ds
    everywhere = answer_data_question(con, ws, dsid, "total revenue")
    north = answer_data_question(con, ws, dsid, "total revenue", context={"filters": {"region": "North"}})
    november = answer_data_question(con, ws, dsid, "total revenue",
                                    context={"filters": {"region": "North"}, "date_from": "2025-11",
                                             "date_to": "2025-11"})
    assert everywhere["value"] > north["value"] > november["value"] == 400
    assert "'North'" in north["sql"]
    with pytest.raises(QueryError):
        answer_data_question(con, ws, dsid, "total revenue", context={"filters": {"nope": "x"}})
    with pytest.raises(QueryError):
        answer_data_question(con, ws, dsid, "total revenue", context={"date_from": "2025-13"})


# ------------------------------------------------------------------ HTTP ---

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "analyst_test.duckdb")
    from app.main import app

    return TestClient(app)


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_http_targets_roles_and_row_rules(client):
    admin = client.post("/api/auth/signup", json={"email": "boss@example.com", "password": "supersecret1",
                                                  "workspace_name": "Acme"}).json()["access_token"]
    ds = client.post("/api/datasets/upload", files={"file": ("s.csv", _csv(_months()), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    r = client.post(f"/api/datasets/{ds}/targets", json={"measure": "revenue", "period": "2025-11", "value": 1100},
                    headers=auth(admin))
    assert r.status_code == 200 and r.json()["status"] == "at_risk"
    assert client.post(f"/api/datasets/{ds}/targets", json={"measure": "revenue", "period": "2025-13", "value": 1},
                       headers=auth(admin)).status_code == 400

    client.post("/api/members", json={"email": "v@example.com", "role": "viewer", "password": "supersecret1"},
                headers=auth(admin))
    vid = next(m["user_id"] for m in client.get("/api/members", headers=auth(admin)).json()
               if m["email"] == "v@example.com")
    client.post(f"/api/datasets/{ds}/rls", json={"user_id": vid, "column_name": "region", "values": ["South"]},
                headers=auth(admin))
    viewer = client.post("/api/auth/login", json={"email": "v@example.com",
                                                  "password": "supersecret1"}).json()["access_token"]
    # viewers read targets but cannot set them; their actuals follow their row rules
    assert client.post(f"/api/datasets/{ds}/targets", json={"measure": "revenue", "period": "2025-11", "value": 1},
                       headers=auth(viewer)).status_code == 403
    mine = client.get(f"/api/datasets/{ds}/targets", headers=auth(viewer)).json()
    assert mine[0]["actual"] == 500
    acts = client.get(f"/api/datasets/{ds}/actions", params={"measure": "revenue"}, headers=auth(viewer)).json()
    assert all("North" not in a["why"] for a in acts["actions"])
    ctx = client.post(f"/api/datasets/{ds}/query",
                      json={"question": "total revenue", "context": {"filters": {"region": "North"}}},
                      headers=auth(viewer))
    assert ctx.status_code == 400   # no North rows exist for this viewer

    tid = mine[0]["target_id"]
    assert client.delete(f"/api/targets/{tid}", headers=auth(viewer)).status_code == 403
    assert client.delete(f"/api/targets/{tid}", headers=auth(admin)).status_code == 200
    assert client.delete(f"/api/targets/{tid}", headers=auth(admin)).status_code == 404

    metric = client.post(f"/api/datasets/{ds}/metrics",
                         json={"name": "Margin", "kind": "ratio", "format": "percent",
                               "definition": {"numerator": {"agg": "sum", "column": "profit"},
                                              "denominator": {"agg": "sum", "column": "revenue"}}},
                         headers=auth(admin)).json()[0]
    r = client.get(f"/api/metrics/{metric['metric_id']}/explain", headers=auth(admin))
    assert r.status_code == 200 and r.json()["kind"] == "ratio"
    assert client.get("/api/metrics/nope/explain", headers=auth(admin)).status_code == 404


def test_migration_creates_the_targets_table():
    import duckdb

    from app.core.migrations import run_migrations

    from app.core import db

    # a database from before targets existed: the base schema without the table
    con = duckdb.connect(":memory:")
    con.execute(db.SCHEMA)
    con.execute("DROP TABLE targets")
    run_migrations(con)
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'targets'").fetchall()}
    assert {"target_id", "workspace_id", "measure", "grain", "period", "value", "filters"} <= cols
