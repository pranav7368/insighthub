"""API keys: a machine credential that can read and write data, and nothing else.

The properties that matter are the restrictions, so most of these tests are
about what a key must NOT be able to do: reach account/team/privacy endpoints,
outlive its creator, exceed its creator's role or rows, or see raw PII.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import apikeys


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "apikeys_test.duckdb")
    from app.main import app

    return TestClient(app)


ROWS = [
    ["date", "customer_email", "region", "revenue"],
    ["2025-01-05", "priya.sharma@acme.com", "North", "100"],
    ["2025-01-06", "raj.patel@corp.io", "South", "200"],
    ["2025-02-07", "anita@example.org", "North", "300"],
]


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def env(client):
    admin = client.post("/api/auth/signup", json={"email": "boss@example.com", "password": "supersecret1",
                                                  "workspace_name": "Acme"}).json()["access_token"]
    ds = client.post("/api/datasets/upload", files={"file": ("s.csv", _csv(ROWS), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    return {"client": client, "admin": admin, "ds": ds}


def new_key(env, **body):
    r = env["client"].post("/api/api-keys", json={"name": "BI sync", **body}, headers=auth(env["admin"]))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- basics ---

def test_key_is_shown_once_and_reads_data(env):
    c, k = env["client"], new_key(env)
    assert k["key"].startswith("ihk_") and k["role"] == "viewer"
    listed = c.get("/api/api-keys", headers=auth(env["admin"])).json()
    assert [x["key_id"] for x in listed] == [k["key_id"]]
    assert "key" not in listed[0] and "secret_hash" not in listed[0]
    assert listed[0]["hint"] == f"ihk_{k['key_id']}_…"

    r = c.get(f"/api/datasets/{env['ds']}/dashboard", headers=auth(k["key"]))
    assert r.status_code == 200 and r.json()["row_count_filtered"] == 3
    assert c.get("/api/api-keys", headers=auth(env["admin"])).json()[0]["last_used_at"] is not None


def test_only_admins_manage_keys(env):
    c = env["client"]
    c.post("/api/members", json={"email": "ed@example.com", "role": "editor", "password": "supersecret1"},
           headers=auth(env["admin"]))
    editor = c.post("/api/auth/login", json={"email": "ed@example.com", "password": "supersecret1"}).json()
    assert c.post("/api/api-keys", json={"name": "x"}, headers=auth(editor["access_token"])).status_code == 403
    assert c.post("/api/api-keys", json={"name": "x", "role": "admin"},
                  headers=auth(env["admin"])).status_code == 400
    assert c.post("/api/api-keys", json={"name": " "}, headers=auth(env["admin"])).status_code == 400


# ------------------------------------------------- what a key cannot do ---

@pytest.mark.parametrize("method,path", [
    ("get", "/api/members"),
    ("post", "/api/auth/change-password"),
    ("post", "/api/auth/revoke-sessions"),
    ("post", "/api/auth/mfa/setup"),
    ("get", "/api/privacy/export/me"),
    ("get", "/api/privacy/export/workspace"),
    ("get", "/api/workspace/security"),
    ("get", "/api/billing"),
    ("get", "/api/api-keys"),
    ("post", "/api/api-keys"),
])
def test_key_cannot_reach_account_team_billing_or_privacy(env, method, path):
    k = new_key(env, role="editor")
    r = getattr(env["client"], method)(path, headers=auth(k["key"]), **({"json": {}} if method == "post" else {}))
    assert r.status_code == 403, (path, r.status_code)


def test_key_role_is_enforced(env):
    c = env["client"]
    viewer, editor = new_key(env), new_key(env, role="editor")
    upload = lambda key: c.post("/api/datasets/upload", files={"file": ("t.csv", _csv(ROWS), "text/csv")},  # noqa: E731
                                headers=auth(key))
    assert upload(viewer["key"]).status_code == 403
    assert upload(editor["key"]).status_code == 200


def test_bad_revoked_and_expired_keys_are_refused_alike(env):
    from app.core import db

    c, k = env["client"], new_key(env)
    url = f"/api/datasets/{env['ds']}/dashboard"
    forged = k["key"][:-4] + ("AAAA" if not k["key"].endswith("AAAA") else "BBBB")
    for bad in (forged, "ihk_0000000000000000_" + "x" * 43, "ihk_nonsense"):
        assert c.get(url, headers=auth(bad)).status_code == 401

    db.connect().execute("UPDATE api_keys SET expires_at = ? WHERE key_id = ?",
                         [_utcnow() - timedelta(minutes=1), k["key_id"]])
    assert c.get(url, headers=auth(k["key"])).status_code == 401

    k2 = new_key(env)
    assert c.delete(f"/api/api-keys/{k2['key_id']}", headers=auth(env["admin"])).status_code == 200
    assert c.get(url, headers=auth(k2["key"])).status_code == 401
    assert c.delete(f"/api/api-keys/{k2['key_id']}", headers=auth(env["admin"])).status_code == 404


def test_expiry_is_set_from_days(env):
    k = new_key(env, expires_in_days=30)
    expires = datetime.fromisoformat(k["expires_at"])
    assert timedelta(days=29) < expires - _utcnow() <= timedelta(days=30)
    assert env["client"].post("/api/api-keys", json={"name": "x", "expires_in_days": 0},
                              headers=auth(env["admin"])).status_code == 400


# ------------------------------------------- a key is bounded by its creator ---

def test_key_follows_its_creator(env):
    """Demote the creator and the key is demoted; remove them and it dies."""
    c = env["client"]
    c.post("/api/members", json={"email": "admin2@example.com", "role": "admin", "password": "supersecret1"},
           headers=auth(env["admin"]))
    admin2 = c.post("/api/auth/login", json={"email": "admin2@example.com", "password": "supersecret1"}).json()
    k = c.post("/api/api-keys", json={"name": "theirs", "role": "editor"},
               headers=auth(admin2["access_token"])).json()
    uid = next(m["user_id"] for m in c.get("/api/members", headers=auth(env["admin"])).json()
               if m["email"] == "admin2@example.com")

    c.patch(f"/api/members/{uid}", json={"role": "viewer"}, headers=auth(env["admin"]))
    up = c.post("/api/datasets/upload", files={"file": ("t.csv", _csv(ROWS), "text/csv")}, headers=auth(k["key"]))
    assert up.status_code == 403

    c.delete(f"/api/members/{uid}", headers=auth(env["admin"]))
    assert c.get(f"/api/datasets/{env['ds']}/dashboard", headers=auth(k["key"])).status_code == 401


def test_key_carries_its_creators_row_rules(env):
    c, k = env["client"], new_key(env)
    me = next(m["user_id"] for m in c.get("/api/members", headers=auth(env["admin"])).json())
    c.post(f"/api/datasets/{env['ds']}/rls", json={"user_id": me, "column_name": "region", "values": ["South"]},
           headers=auth(env["admin"]))
    dash = c.get(f"/api/datasets/{env['ds']}/dashboard", headers=auth(k["key"])).json()
    assert dash["row_count_filtered"] == 1


def test_key_never_sees_raw_pii_even_when_an_admin_made_it(env):
    c, k = env["client"], new_key(env)
    url = f"/api/datasets/{env['ds']}/export.csv"
    assert "priya.sharma@acme.com" in c.get(url, headers=auth(env["admin"])).text
    body = c.get(url, headers=auth(k["key"])).text
    assert "priya.sharma@acme.com" not in body and "pr***@acme.com" in body
    # and the exemption does not leak into the next (session) request
    assert "priya.sharma@acme.com" in c.get(url, headers=auth(env["admin"])).text


def test_erasing_the_creator_deletes_their_keys_and_exports_omit_hashes(env):
    from app.core import db

    c, k = env["client"], new_key(env)
    export = c.get("/api/privacy/export/workspace", headers=auth(env["admin"])).json()
    assert export["tables"]["api_keys"][0]["key_id"] == k["key_id"]
    assert "secret_hash" not in export["tables"]["api_keys"][0]

    from app.core.datarights import erase_member

    con = db.connect()
    me = con.execute("SELECT user_id, workspace_id FROM users WHERE email = 'boss@example.com'").fetchone()
    erase_member(con, me[1], me[0])
    assert con.execute("SELECT count(*) FROM api_keys").fetchone()[0] == 0


def test_path_allowlist():
    assert apikeys.path_allowed("/api/datasets/ds_1/dashboard")
    assert apikeys.path_allowed("/api/ask")
    assert not apikeys.path_allowed("/api/asking")          # a prefix match must end at a segment
    assert not apikeys.path_allowed("/api/members")
    assert not apikeys.path_allowed(None)
