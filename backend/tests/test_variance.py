"""Variance: period selection (incl. like-for-like), waterfall reconciliation,
the auto "biggest mover" split, and the price/volume/mix identity."""

import csv
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.analytics.drill import DrillError
from app.analytics.variance import (
    explain_variance, guess_volume_measure, latest_period, price_volume_mix, shift_period,
)
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# Feb -> Mar. Region carries the story (North +300); product is spread out.
# units x price: Widget 10/unit, Gadget 50/unit (Gadget's price rises in Mar).
DATA = [
    ["date", "region", "product", "revenue", "units"],
    ["2025-02-03", "North", "Widget", "100", "10"],
    ["2025-02-10", "South", "Gadget", "200", "4"],
    ["2025-02-20", "East", "Widget", "100", "10"],
    ["2025-03-03", "North", "Widget", "200", "20"],
    ["2025-03-04", "North", "Gadget", "200", "4"],     # Gadget 50/unit
    ["2025-03-10", "South", "Gadget", "220", "4"],     # Gadget 55/unit
    ["2025-03-31", "East", "Widget", "100", "10"],
]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(DATA))
    return con, "ws_a", res.dataset_id


# ------------------------------------------------------------ periods ---

def test_period_shifts():
    assert shift_period(date(2025, 3, 1), date(2025, 3, 31), "previous") == (date(2025, 2, 1), date(2025, 2, 28))
    assert shift_period(date(2025, 1, 1), date(2025, 3, 31), "previous") == (date(2024, 10, 1), date(2024, 12, 31))
    assert shift_period(date(2025, 3, 1), date(2025, 3, 31), "year_ago") == (date(2024, 3, 1), date(2024, 3, 31))
    assert shift_period(date(2025, 3, 3), date(2025, 3, 9), "previous") == (date(2025, 2, 24), date(2025, 3, 2))
    assert shift_period(date(2024, 2, 29), date(2024, 2, 29), "year_ago") == (date(2023, 2, 28), date(2023, 2, 28))
    assert latest_period(date(2025, 3, 12), "quarter") == (date(2025, 1, 1), date(2025, 3, 31))
    assert latest_period(date(2025, 3, 12), "week") == (date(2025, 3, 10), date(2025, 3, 16))


# ----------------------------------------------------------- variance ---

def test_waterfall_reconciles_and_picks_the_concentrated_dimension(ds):
    con, ws, dsid = ds
    r = explain_variance(con, ws, dsid, measure="revenue")
    assert r["a"]["label"] == "Feb 2025" and r["b"]["label"] == "Mar 2025"
    assert (r["a"]["value"], r["b"]["value"], r["delta"]) == (400, 720, 320)
    assert r["dimension"] == "region" == r["auto_dimension"]
    steps = {s["name"]: s["delta"] for s in r["steps"]}
    assert steps == {"North": 300, "South": 20, "East": 0}
    # the steps always add up to the change
    assert sum(s["delta"] for s in r["steps"]) + (r["other"]["delta"] if r["other"] else 0) == r["delta"]
    assert "rose 80.0%" in r["summary"]
    assert "North accounts for +₹300 (94% of the move)" in r["summary"]


def test_tail_folds_into_other_and_still_reconciles(ds):
    con, ws, dsid = ds
    r = explain_variance(con, ws, dsid, measure="revenue", dimension="region", limit=1)
    assert [s["name"] for s in r["steps"]] == ["North"]
    assert r["other"] == {"count": 2, "a": 300, "b": 320, "delta": 20, "share_of_change": pytest.approx(20 / 320)}


def test_blank_members_are_kept_so_it_reconciles(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "region", "revenue"], ["2025-01-05", "North", "100"], ["2025-01-06", "", "50"],
            ["2025-02-05", "North", "100"], ["2025-02-06", "", "90"]]
    dsid = ingest_upload(con, "ws_a", "b.csv", _csv(rows)).dataset_id
    r = explain_variance(con, "ws_a", dsid, measure="revenue", dimension="region")
    assert r["delta"] == 40
    blank = next(s for s in r["steps"] if s["blank"])
    assert blank["delta"] == 40


def test_explicit_period_and_year_ago(ds):
    con, ws, dsid = ds
    r = explain_variance(con, ws, dsid, measure="revenue", date_from="2025-03", date_to="2025-03",
                         compare="year_ago")
    assert r["a"]["label"] == "Mar 2024" and r["a"]["value"] == 0 and r["pct"] is None


def test_partial_latest_period_is_compared_like_for_like(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "region", "revenue"],
            ["2025-02-05", "North", "100"], ["2025-02-25", "North", "900"],   # late-Feb sale
            ["2025-03-04", "North", "120"], ["2025-03-10", "South", "1"]]     # data ends 10 Mar
    dsid = ingest_upload(con, "ws_a", "p.csv", _csv(rows)).dataset_id
    r = explain_variance(con, "ws_a", dsid, measure="revenue")
    assert r["like_for_like"] is True
    assert (r["b"]["to"], r["a"]["to"]) == ("2025-03-10", "2025-02-10")
    # 1–10 Feb (100) vs 1–10 Mar (121), not all of February (1000)
    assert (r["a"]["value"], r["b"]["value"]) == (100, 121)
    assert "like for like" in r["note"]


def test_variance_respects_slice_filters_and_validates(ds):
    con, ws, dsid = ds
    r = explain_variance(con, ws, dsid, measure="revenue", filters={"region": "North"})
    assert r["delta"] == 300 and r["dimension"] == "product"
    assert explain_variance(con, ws, dsid, agg="count")["delta"] == 1
    with pytest.raises(DrillError):
        explain_variance(con, ws, dsid, measure="revenue", agg="avg")
    with pytest.raises(DrillError):
        explain_variance(con, ws, dsid, measure="revenue", filters={"region": "North"}, dimension="region")
    with pytest.raises(DrillError):
        explain_variance(con, ws, dsid, measure="revenue", compare="sideways")


# ------------------------------------------------------- price/vol/mix ---

def test_price_volume_mix_adds_up_exactly(ds):
    con, ws, dsid = ds
    assert guess_volume_measure({"revenue": None, "units": None}, "revenue") == "units"
    r = price_volume_mix(con, ws, dsid, measure="revenue")
    assert r["volume"] == "units" and r["dimension"] == "product"
    e = r["effects"]
    assert e["volume"] + e["mix"] + e["price"] + e["unexplained"] == pytest.approx(r["delta"]) == 320
    assert e["unexplained"] == 0
    # Gadget's price went 50 -> 52.5 on 8 units: +20 of price effect, nothing else
    assert e["price"] == pytest.approx(20)
    # volume: 24 -> 38 units at Feb's average price (400 / 24)
    assert e["volume"] == pytest.approx((38 - 24) * 400 / 24)


def test_price_volume_mix_reports_what_it_cannot_explain(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "product", "revenue", "units"],
            ["2025-01-05", "A", "100", "10"], ["2025-01-06", "B", "50", "5"],
            ["2025-02-05", "A", "100", "10"], ["2025-02-06", "Fee", "30", "0"]]   # revenue, no units
    dsid = ingest_upload(con, "ws_a", "u.csv", _csv(rows)).dataset_id
    r = price_volume_mix(con, "ws_a", dsid, measure="revenue", volume="units")
    e = r["effects"]
    assert e["volume"] + e["mix"] + e["price"] + e["unexplained"] == pytest.approx(r["delta"])
    assert e["unexplained"] != 0


def test_price_volume_mix_with_nothing_left_to_mix_across(ds):
    con, ws, dsid = ds
    r = price_volume_mix(con, ws, dsid, measure="revenue", volume="units",
                         filters={"region": "South", "product": "Gadget"})
    e = r["effects"]
    assert r["dimension"] is None and e["mix"] == 0
    # South Gadget: 4 units at 50 -> 4 units at 55: all price
    assert (e["volume"], e["price"]) == (0, pytest.approx(20))


def test_price_volume_mix_validates(ds):
    con, ws, dsid = ds
    with pytest.raises(DrillError):
        price_volume_mix(con, ws, dsid, measure="revenue", volume="revenue")
    with pytest.raises(DrillError):
        price_volume_mix(con, ws, dsid, measure="revenue", volume="units", dimension="nope")


# --------------------------------------------------------------- HTTP ---

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "variance_test.duckdb")
    from app.main import app

    return TestClient(app)


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_endpoints_and_row_rules(client):
    admin = client.post("/api/auth/signup", json={"email": "boss@example.com", "password": "supersecret1",
                                                  "workspace_name": "Acme"}).json()["access_token"]
    ds = client.post("/api/datasets/upload", files={"file": ("s.csv", _csv(DATA), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    r = client.get(f"/api/datasets/{ds}/variance", params={"measure": "revenue"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["delta"] == 320
    r = client.get(f"/api/datasets/{ds}/pvm", params={"measure": "revenue"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["volume"] == "units"
    assert client.get(f"/api/datasets/{ds}/variance", params={"agg": "avg"},
                      headers=auth(admin)).status_code == 400

    client.post("/api/members", json={"email": "south@example.com", "role": "viewer",
                                      "password": "supersecret1"}, headers=auth(admin))
    vid = next(m["user_id"] for m in client.get("/api/members", headers=auth(admin)).json()
               if m["email"] == "south@example.com")
    client.post(f"/api/datasets/{ds}/rls", json={"user_id": vid, "column_name": "region", "values": ["South"]},
                headers=auth(admin))
    viewer = client.post("/api/auth/login", json={"email": "south@example.com",
                                                  "password": "supersecret1"}).json()["access_token"]
    v = client.get(f"/api/datasets/{ds}/variance", params={"measure": "revenue", "dimension": "product"},
                   headers=auth(viewer)).json()
    assert v["delta"] == 20 and {s["name"] for s in v["steps"]} == {"Gadget"}
    north = client.get(f"/api/datasets/{ds}/variance",
                       params={"measure": "revenue", "filters": json.dumps({"region": "North"})},
                       headers=auth(viewer)).json()
    assert north["delta"] == 0 and north["a"]["value"] == 0


def test_summary_explains_a_driver_bigger_than_the_whole_change(con):
    """North -300, South +250: the total fell 50 but North alone fell 300.
    "600% of the move" is correct arithmetic and confusing prose."""
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "region", "revenue"],
            ["2025-01-05", "North", "400"], ["2025-01-06", "South", "100"],
            ["2025-02-05", "North", "100"], ["2025-02-06", "South", "350"]]
    dsid = ingest_upload(con, "ws_a", "o.csv", _csv(rows)).dataset_id
    s = explain_variance(con, "ws_a", dsid, measure="revenue", dimension="region")["summary"]
    assert "% of the move" not in s
    assert "North alone moved −₹300, more than the whole change" in s
    assert "other region values rose and offset part of it" in s
