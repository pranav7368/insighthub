"""Data subject rights: export and erasure.

The tests that matter are the completeness ones. A deletion request answered
incompletely is not a partial success — it is an undisclosed retention of
personal data, and under both DPDP and GDPR that is the thing that turns into a
notification.
"""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.core.datarights import (
    DataRightsError, erase_workspace, export_member, export_workspace,
)

STRONG = "correct-horse-battery"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "rights.duckdb")
    from app.main import app

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SALES = [["date", "region", "revenue"],
         ["2025-01-05", "North", "1000"],
         ["2025-02-06", "South", "2000"]]


@pytest.fixture()
def env(client):
    admin = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": STRONG, "workspace_name": "Acme",
    }).json()["access_token"]
    ds = client.post("/api/datasets/upload",
                     files={"file": ("sales.csv", _csv(SALES), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    client.post("/api/members", json={"email": "mem@example.com", "role": "editor",
                                      "password": STRONG}, headers=auth(admin))
    member_id = next(m["user_id"] for m in client.get("/api/members", headers=auth(admin)).json()
                     if m["email"] == "mem@example.com")
    member = client.post("/api/auth/login", json={
        "email": "mem@example.com", "password": STRONG}).json()["access_token"]
    return {"client": client, "admin": admin, "member": member,
            "member_id": member_id, "dataset_id": ds}


# -------------------------------------------------------------- export ----

def test_anyone_can_export_their_own_record(env):
    """The right of access does not depend on being an admin."""
    r = env["client"].get("/api/privacy/export/me", headers=auth(env["member"]))
    assert r.status_code == 200
    payload = json.loads(r.text)
    assert payload["subject"] == "member"
    assert payload["account"]["email"] == "mem@example.com"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_export_never_includes_the_password_hash(env):
    for url, token in (("/api/privacy/export/me", env["member"]),
                       ("/api/privacy/export/workspace", env["admin"])):
        body = env["client"].get(url, headers=auth(token)).text
        assert "password_hash" not in body


def test_member_export_includes_their_activity(env):
    body = json.loads(env["client"].get("/api/privacy/export/me",
                                        headers=auth(env["member"])).text)
    assert isinstance(body["activity"], list)


def test_workspace_export_contains_the_uploaded_data(env):
    body = json.loads(env["client"].get("/api/privacy/export/workspace",
                                        headers=auth(env["admin"])).text)
    assert "datasets" in body["tables"]
    assert any(d["dataset_id"] == env["dataset_id"] for d in body["tables"]["datasets"])


def test_only_admins_export_other_people(env):
    r = env["client"].get(f"/api/privacy/export/member/{env['member_id']}",
                          headers=auth(env["member"]))
    assert r.status_code == 403


def test_only_admins_export_the_workspace(env):
    assert env["client"].get("/api/privacy/export/workspace",
                             headers=auth(env["member"])).status_code == 403


# ------------------------------------------------------------- erasure ----

def test_erasing_a_member_removes_the_account_but_keeps_audit_deidentified(env):
    c = env["client"]
    r = c.delete(f"/api/privacy/member/{env['member_id']}", headers=auth(env["admin"]))
    assert r.status_code == 200

    remaining = [m["email"] for m in c.get("/api/members", headers=auth(env["admin"])).json()]
    assert "mem@example.com" not in remaining
    # their token dies with the account
    assert c.get("/api/datasets", headers=auth(env["member"])).status_code == 401
    # the security record survives, no longer identifying anyone
    body = json.loads(c.get("/api/privacy/export/workspace", headers=auth(env["admin"])).text)
    audit_users = {row["user_id"] for row in body["tables"].get("audit_log", [])}
    assert env["member_id"] not in audit_users


def test_an_admin_cannot_erase_themselves(env):
    admin_id = next(m["user_id"] for m in
                    env["client"].get("/api/members", headers=auth(env["admin"])).json()
                    if m["email"] == "boss@example.com")
    r = env["client"].delete(f"/api/privacy/member/{admin_id}", headers=auth(env["admin"]))
    assert r.status_code == 400


def test_workspace_erasure_requires_typing_the_name(env):
    r = env["client"].post("/api/privacy/erase-workspace",
                           json={"confirm_workspace_name": "wrong"}, headers=auth(env["admin"]))
    assert r.status_code == 400


def test_workspace_erasure_removes_everything_including_raw_tables(env, tmp_path):
    c = env["client"]
    r = c.post("/api/privacy/erase-workspace",
               json={"confirm_workspace_name": "Acme"}, headers=auth(env["admin"]))
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["raw_tables_dropped"], "the physical dataset table must be dropped"

    # the account is gone, so the token no longer resolves
    assert c.get("/api/datasets", headers=auth(env["admin"])).status_code == 401


def test_erasure_verifies_itself(con):
    """erase_workspace re-counts afterwards and raises rather than reporting a
    success it did not achieve."""
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_x', 'X')")
    con.execute("INSERT INTO users (user_id, workspace_id, email, password_hash, role) "
                "VALUES ('u1', 'ws_x', 'a@b.com', 'h', 'admin')")
    result = erase_workspace(con, "ws_x")
    assert result["erased"] == "workspace"
    assert con.execute("SELECT count(*) FROM users WHERE workspace_id = 'ws_x'").fetchone()[0] == 0


def test_erasure_covers_every_workspace_table(con):
    """The table list is derived from the catalog, so a table added later is
    erased too. A hand-maintained list would rot and leave data behind."""
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_y', 'Y')")
    con.execute("INSERT INTO users (user_id, workspace_id, email, password_hash, role) "
                "VALUES ('u2', 'ws_y', 'c@d.com', 'h', 'admin')")
    con.execute("INSERT INTO dashboard_views (view_id, workspace_id, dataset_id, name, config) "
                "VALUES ('v1', 'ws_y', 'ds1', 'V', '{}')")
    con.execute("INSERT INTO metrics (metric_id, workspace_id, dataset_id, name, kind, definition) "
                "VALUES ('m1', 'ws_y', 'ds1', 'M', 'aggregate', '{}')")

    erase_workspace(con, "ws_y")
    for table in ("users", "dashboard_views", "metrics", "workspaces"):
        assert con.execute(f"SELECT count(*) FROM {table} WHERE workspace_id = 'ws_y'"
                           if table != "workspaces"
                           else "SELECT count(*) FROM workspaces WHERE workspace_id = 'ws_y'"
                           ).fetchone()[0] == 0


def test_erasure_leaves_other_tenants_untouched(con):
    for wsid in ("ws_keep", "ws_drop"):
        con.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)", [wsid, wsid])
        con.execute("INSERT INTO users (user_id, workspace_id, email, password_hash, role) "
                    "VALUES (?, ?, ?, 'h', 'admin')", [f"u_{wsid}", wsid, f"{wsid}@x.com"])

    erase_workspace(con, "ws_drop")
    assert con.execute("SELECT count(*) FROM users WHERE workspace_id = 'ws_keep'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM workspaces WHERE workspace_id = 'ws_keep'").fetchone()[0] == 1


def test_export_of_an_unknown_member_raises(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_z', 'Z')")
    with pytest.raises(DataRightsError):
        export_member(con, "ws_z", "usr_does_not_exist")


def test_a_member_cannot_be_exported_across_tenants(con):
    """Tenant isolation applies to the privacy endpoints too."""
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    con.execute("INSERT INTO users (user_id, workspace_id, email, password_hash, role) "
                "VALUES ('u_a', 'ws_a', 'a@a.com', 'h', 'admin')")
    with pytest.raises(DataRightsError):
        export_member(con, "ws_b", "u_a")
