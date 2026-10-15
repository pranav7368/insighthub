"""Drill-down: the inspector's numbers, grains, comparisons, breakdown tail,
record paging — and, through HTTP, that row rules and PII masking follow the
member all the way down to the raw rows."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.analytics.drill import (
    DrillError, breakdown, inspect, period_bounds, records, records_csv, year_ago,
)
from app.analytics.engine import DatasetNotFound, compute_dashboard
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# 2024-03 (year-ago), 2025-02 and 2025-03, three regions
DATA = [
    ["date", "region", "product", "revenue"],
    ["2024-03-10", "North", "Widget", "50"],
    ["2025-02-03", "North", "Widget", "100"],
    ["2025-02-04", "South", "Gadget", "200"],
    ["2025-03-05", "North", "Gadget", "300"],
    ["2025-03-06", "South", "Widget", "100"],
    ["2025-03-31", "East", "Widget", "50"],
]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(DATA))
    return con, "ws_a", res.dataset_id


# ------------------------------------------------------------- inspect ---

def test_inspect_headline_matches_the_rows(ds):
    con, ws, dsid = ds
    r = inspect(con, ws, dsid, measure="revenue")
    assert r["value"] == 800 and r["row_count"] == 6
    assert r["stats"]["min"] == 50 and r["stats"]["max"] == 300
    assert "Sum of revenue across 6 rows" in r["explanation"]
    assert 'FROM "sales"' in r["sql"] and "SUM(" in r["sql"]


def test_inspect_respects_filters_and_dates(ds):
    con, ws, dsid = ds
    r = inspect(con, ws, dsid, measure="revenue", filters={"region": "North"},
                date_from="2025-03", date_to="2025-03")
    assert r["value"] == 300 and r["row_count"] == 1
    assert "region = North" in r["explanation"] and "in 2025-03" in r["explanation"]
    # the member's own filter values are shown in the SQL, inlined for reading
    assert "'North'" in r["sql"]


def test_inspect_other_aggregations(ds):
    con, ws, dsid = ds
    assert inspect(con, ws, dsid, measure="revenue", agg="avg")["value"] == pytest.approx(800 / 6)
    assert inspect(con, ws, dsid, agg="count")["value"] == 6
    assert inspect(con, ws, dsid, measure="revenue", agg="max")["value"] == 300
    with pytest.raises(DrillError):
        inspect(con, ws, dsid, measure="revenue", agg="drop table")


def test_trend_comparison_previous_and_year_ago(ds):
    con, ws, dsid = ds
    trend = inspect(con, ws, dsid, measure="revenue")["trend"]
    periods = [p["period"] for p in trend["points"]]
    assert periods == ["2024-03", "2025-02", "2025-03"]
    cmp_ = trend["comparison"]
    assert cmp_["value"] == 450
    assert cmp_["previous"]["period"] == "2025-02" and cmp_["previous"]["delta"] == 150
    assert cmp_["year_ago"]["period"] == "2024-03" and cmp_["year_ago"]["value"] == 50
    # each point carries the bounds a drill into it sends back
    assert trend["points"][-1]["from"] == "2025-03" and trend["points"][-1]["to"] == "2025-03"


@pytest.mark.parametrize("grain,expected_last", [
    ("day", "2025-03-31"), ("week", "2025-03-31"), ("quarter", "2025-Q1"), ("year", "2025"),
])
def test_every_grain(ds, grain, expected_last):
    con, ws, dsid = ds
    trend = inspect(con, ws, dsid, measure="revenue", grain=grain)["trend"]
    assert trend["points"][-1]["period"] == expected_last
    assert sum(p["value"] for p in trend["points"]) == 800


def test_partial_latest_period_is_flagged(ds):
    con, ws, dsid = ds
    # data runs to 31 Mar -> March is complete; Q1 is complete too
    assert inspect(con, ws, dsid, measure="revenue")["trend"]["latest_period_partial"] is False
    # but the year 2025 is not
    r = inspect(con, ws, dsid, measure="revenue", grain="year")
    assert r["trend"]["latest_period_partial"] is True
    assert any("incomplete" in n for n in r["notes"])
    # North's last sale is 5 Mar, but the data runs to 31 Mar: March is
    # complete for North too — a quiet segment is not a partial period
    north = inspect(con, ws, dsid, measure="revenue", filters={"region": "North"})
    assert north["trend"]["latest_period_partial"] is False


def test_period_helpers():
    assert period_bounds("2025-Q2", "quarter") == ("2025-04", "2025-06")
    assert period_bounds("2025-03-03", "week") == ("2025-03-03", "2025-03-09")
    assert period_bounds("2025", "year") == ("2025-01", "2025-12")
    assert year_ago("2024-02-29", "day") == "2023-02-28"
    assert year_ago("2025-Q1", "quarter") == "2024-Q1"


def test_contributors_skip_pinned_dimensions(ds):
    con, ws, dsid = ds
    r = inspect(con, ws, dsid, measure="revenue", filters={"region": "North"})
    dims = [c["dimension"] for c in r["contributors"]]
    assert "region" not in dims and "product" in dims
    product = next(c for c in r["contributors"] if c["dimension"] == "product")
    shares = {i["name"]: i["share_pct"] for i in product["items"]}
    assert shares == {"Gadget": pytest.approx(300 / 450 * 100, abs=0.1),
                      "Widget": pytest.approx(150 / 450 * 100, abs=0.1)}


def test_bad_input_is_rejected(ds):
    con, ws, dsid = ds
    with pytest.raises(DrillError):
        inspect(con, ws, dsid, filters={"no_such_column": "x"})
    with pytest.raises(DrillError):
        inspect(con, ws, dsid, date_from="2025-13")
    with pytest.raises(DrillError):
        inspect(con, ws, dsid, grain="fortnight")
    with pytest.raises(DatasetNotFound):
        inspect(con, "ws_b", dsid)


# ----------------------------------------------------------- breakdown ---

def test_breakdown_folds_the_tail_into_others(ds):
    con, ws, dsid = ds
    r = breakdown(con, ws, dsid, dimension="region", measure="revenue", limit=1)
    assert [i["name"] for i in r["items"]] == ["North"]
    assert r["others"] == {"count": 2, "value": 350, "rows": 3,
                           "share_pct": pytest.approx(350 / 800 * 100, abs=0.1)}
    full = breakdown(con, ws, dsid, dimension="region", measure="revenue")
    assert full["others"] is None and full["distinct"] == 3


def test_breakdown_tail_is_right_for_non_additive_aggregations(ds):
    con, ws, dsid = ds
    r = breakdown(con, ws, dsid, dimension="region", measure="revenue", agg="avg", limit=1)
    # South (200, 100) and East (50) averaged together, not total minus shown
    assert r["others"]["value"] == pytest.approx(350 / 3)
    assert r["items"][0]["share_pct"] is None


def test_dashboard_breakdown_reports_others_and_true_shares(ds):
    con, ws, dsid = ds
    # each region appears 8 times so it reads as a category, not an identifier
    rows = [["region", "revenue"]] + [[f"R{i:02d}", str(100 - i)] for i in range(25) for _ in range(8)]
    many = ingest_upload(con, ws, "many.csv", _csv(rows)).dataset_id
    bd = compute_dashboard(con, ws, many)["breakdowns"]["region"]
    assert len(bd["data"]) == 20
    assert bd["others"]["count"] == 5
    grand = sum(100 - i for i in range(25))
    assert bd["data"][0]["share_pct"] == pytest.approx(100 / grand * 100, abs=0.1)


# ------------------------------------------------------------- records ---

def test_records_page_and_sort(ds):
    con, ws, dsid = ds
    first = records(con, ws, dsid, sort="revenue", desc=True, page_size=2)
    names = [c["name"] for c in first["columns"]]
    assert first["total"] == 6 and len(first["rows"]) == 2
    assert first["rows"][0][names.index("revenue")] == 300
    last = records(con, ws, dsid, sort="revenue", desc=True, page_size=2, page=3)
    assert len(last["rows"]) == 2
    with pytest.raises(DrillError):
        records(con, ws, dsid, sort="1; DROP TABLE x")


def test_records_follow_the_slice(ds):
    con, ws, dsid = ds
    r = records(con, ws, dsid, filters={"region": "South"}, date_from="2025-03")
    assert r["total"] == 1
    text = records_csv(con, ws, dsid, filters={"region": "South"})
    assert text.count("South") == 2 and "North" not in text


# ---------------------------------------------------------------- HTTP ---

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "drill_test.duckdb")
    from app.main import app

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


PEOPLE = [
    ["date", "region", "email", "revenue"],
    ["2025-01-05", "North", "asha@example.com", "1000"],
    ["2025-01-06", "South", "ravi@example.com", "2000"],
    ["2025-02-07", "North", "meera@example.com", "4000"],
]


@pytest.fixture()
def env(client):
    admin = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": "supersecret1", "workspace_name": "Acme",
    }).json()["access_token"]
    ds = client.post("/api/datasets/upload",
                     files={"file": ("people.csv", _csv(PEOPLE), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    client.post("/api/members", json={"email": "north@example.com", "role": "viewer",
                                      "password": "supersecret1"}, headers=auth(admin))
    members = client.get("/api/members", headers=auth(admin)).json()
    viewer_id = next(m["user_id"] for m in members if m["email"] == "north@example.com")
    viewer = client.post("/api/auth/login", json={
        "email": "north@example.com", "password": "supersecret1"}).json()["access_token"]
    r = client.post(f"/api/datasets/{ds}/rls",
                    json={"user_id": viewer_id, "column_name": "region", "values": ["North"]},
                    headers=auth(admin))
    assert r.status_code == 200, r.text
    return client, admin, viewer, ds


def test_endpoints_answer_and_validate(env):
    client, admin, _, ds = env
    r = client.get(f"/api/datasets/{ds}/inspect", params={"measure": "revenue"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["value"] == 7000
    r = client.get(f"/api/datasets/{ds}/breakdown",
                   params={"dimension": "region", "filters": json.dumps({"region": "North"})},
                   headers=auth(admin))
    assert r.status_code == 200 and [i["name"] for i in r.json()["items"]] == ["North"]
    assert client.get(f"/api/datasets/{ds}/inspect", params={"filters": "[1]"},
                      headers=auth(admin)).status_code == 400
    assert client.get(f"/api/datasets/{ds}/rows", params={"sort": "nope"},
                      headers=auth(admin)).status_code == 400
    assert client.get("/api/datasets/nope/rows", headers=auth(admin)).status_code == 404
    assert client.get(f"/api/datasets/{ds}/rows").status_code == 401


def test_row_rules_reach_every_drill_path(env):
    client, _, viewer, ds = env
    h = auth(viewer)
    insp = client.get(f"/api/datasets/{ds}/inspect", params={"measure": "revenue"}, headers=h).json()
    assert insp["value"] == 5000
    assert any("row-access rules" in n for n in insp["notes"])
    # the rule's values are never echoed into the displayed SQL
    assert "North" not in insp["sql"]
    bd = client.get(f"/api/datasets/{ds}/breakdown", params={"dimension": "region"}, headers=h).json()
    assert [i["name"] for i in bd["items"]] == ["North"]
    rows = client.get(f"/api/datasets/{ds}/rows", headers=h).json()
    assert rows["total"] == 2
    text = client.get(f"/api/datasets/{ds}/rows.csv", headers=h).text
    assert "South" not in text
    # asking for a forbidden region explicitly still yields nothing
    south = client.get(f"/api/datasets/{ds}/rows",
                       params={"filters": json.dumps({"region": "South"})}, headers=h).json()
    assert south["total"] == 0


def test_raw_rows_are_masked_for_non_admins(env):
    client, admin, viewer, ds = env
    admin_rows = client.get(f"/api/datasets/{ds}/rows", headers=auth(admin)).json()
    assert "asha@example.com" in json.dumps(admin_rows)
    viewer_rows = client.get(f"/api/datasets/{ds}/rows", headers=auth(viewer)).json()
    assert "asha@example.com" not in json.dumps(viewer_rows)
    assert "meera@example.com" not in client.get(f"/api/datasets/{ds}/rows.csv",
                                                headers=auth(viewer)).text
