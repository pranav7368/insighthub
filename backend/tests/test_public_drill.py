"""Share links: drill-down for anonymous visitors, and the masking guarantee.

A public link is the least trusted surface in the product, so these go
through HTTP: masking regardless of who made the link, a visitor confined to
what was shared, and nothing row-level reachable at all.
"""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.analytics.sharing import ShareError, scope_to_share


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "public_drill.duckdb")
    from app.main import app

    return TestClient(app)


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def auth(t):
    return {"Authorization": f"Bearer {t}"}


PEOPLE = [
    ["date", "customer_name", "email", "region", "revenue"],
    ["2025-01-05", "Priya Sharma", "priya.sharma@acme.com", "North", "1000"],
    ["2025-01-06", "Raj Patel", "raj.patel@corp.io", "South", "2000"],
    ["2025-02-07", "Anita Desai", "anita@example.org", "East", "3000"],
    ["2025-02-08", "Priya Sharma", "priya.sharma@acme.com", "North", "4000"],
    ["2025-03-09", "Raj Patel", "raj.patel@corp.io", "South", "5000"],
    ["2025-03-10", "Anita Desai", "anita@example.org", "North", "500"],
]
RAW = ["priya.sharma@acme.com", "raj.patel@corp.io", "Priya Sharma", "Raj Patel"]


@pytest.fixture()
def env(client):
    admin = client.post("/api/auth/signup", json={"email": "boss@example.com", "password": "supersecret1",
                                                  "workspace_name": "Acme"}).json()["access_token"]
    ds = client.post("/api/datasets/upload", files={"file": ("people.csv", _csv(PEOPLE), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]

    def share(config=None):
        view_id = None
        if config:
            view_id = client.post(f"/api/datasets/{ds}/views", json={"name": "v", "config": config},
                                  headers=auth(admin)).json()["view_id"]
        return client.post(f"/api/datasets/{ds}/shares", json={"view_id": view_id},
                           headers=auth(admin)).json()["token"]

    return client, admin, ds, share


# ------------------------------------------------- the masking guarantee ---

def test_a_link_made_by_an_admin_is_still_masked(env):
    """Admins see raw PII in the app; an admin's public link must not hand it
    to anyone with the URL. This leaked before public reads forced masking."""
    client, admin, ds, share = env
    token = share()
    inside = client.get(f"/api/datasets/{ds}/dashboard", headers=auth(admin)).text
    assert "priya.sharma@acme.com" in inside                       # the admin still sees raw values
    for path in ("dashboard", "inspect?measure=revenue",
                 "breakdown?dimension=customer_name&measure=revenue",
                 "variance?measure=revenue&dimension=customer_name"):
        r = client.get(f"/api/public/{token}/{path}")
        assert r.status_code == 200, (path, r.text)      # an answer, not an error with nothing in it
        body = r.text
        assert "@" in body or "*" in body                # the PII column is there, just masked
        for raw in RAW:
            assert raw not in body, (path, raw)


# ------------------------------------------------------------- scoping ---

def test_scope_rules():
    cfg = {"filters": {"region": "North"}, "date_from": "2025-02", "date_to": "2025-03"}
    assert scope_to_share(cfg, {"customer_name": "x"}, None, None) == (
        {"customer_name": "x", "region": "North"}, "2025-02", "2025-03")
    # narrowing inside the shared range is fine; widening is clamped back
    assert scope_to_share(cfg, {}, "2025-03", "2025-03")[1:] == ("2025-03", "2025-03")
    assert scope_to_share(cfg, {}, "2024-01", "2026-12")[1:] == ("2025-02", "2025-03")
    with pytest.raises(ShareError):
        scope_to_share(cfg, {"region": "South"}, None, None)        # cannot swap the pinned filter
    with pytest.raises(ShareError):
        scope_to_share({"date_from": "2025-03"}, {}, "2025-01", "2025-01")


def test_a_visitor_can_narrow_but_never_widen(env):
    client, _, _, share = env
    token = share({"filters": {"region": "North"}})
    north = client.get(f"/api/public/{token}/inspect", params={"measure": "revenue"}).json()
    assert north["value"] == 5500 and north["context"]["filters"] == {"region": "North"}
    # another region is refused rather than silently answered
    r = client.get(f"/api/public/{token}/inspect",
                   params={"measure": "revenue", "filters": json.dumps({"region": "South"})})
    assert r.status_code == 400
    # a breakdown by region only ever shows the shared one
    bd = client.get(f"/api/public/{token}/breakdown", params={"dimension": "region"}).json()
    assert [i["name"] for i in bd["items"]] == ["North"]


def test_dates_are_clamped_and_change_analysis_needs_an_open_range(env):
    client, _, _, share = env
    token = share({"date_from": "2025-02", "date_to": "2025-03"})
    wide = client.get(f"/api/public/{token}/inspect",
                      params={"measure": "revenue", "date_from": "2024-01", "date_to": "2026-12"}).json()
    assert wide["value"] == 12500 and wide["context"]["date_from"] == "2025-02"
    # comparing with the previous period would read January, which was not shared
    r = client.get(f"/api/public/{token}/variance", params={"measure": "revenue"})
    assert r.status_code == 400 and "date-limited" in r.json()["detail"]
    assert client.get(f"/api/public/{token}/dashboard").json()["meta"]["date_limited"] is True

    open_token = share()
    v = client.get(f"/api/public/{open_token}/variance", params={"measure": "revenue"}).json()
    assert v["delta"] == 5500 - 7000


def test_nothing_row_level_is_public(env):
    client, _, _, share = env
    token = share()
    for path in ("rows", "rows.csv", "query", "targets", "actions", "pvm"):
        assert client.get(f"/api/public/{token}/{path}").status_code in (404, 405)


def test_revoked_and_unknown_links_answer_nothing(env):
    client, admin, _, share = env
    token = share()
    assert client.get(f"/api/public/{token}/inspect").status_code == 200
    client.delete(f"/api/shares/{token}", headers=auth(admin))
    assert client.get(f"/api/public/{token}/inspect").status_code == 404
    assert client.get("/api/public/not-a-token/breakdown", params={"dimension": "region"}).status_code == 404
