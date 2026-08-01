"""Workspace-wide MFA requirement.

The whole risk in this feature is a lockout: a requirement that cannot be
satisfied because satisfying it needs the access being withheld. Most of these
tests exist to prove that cannot happen.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import mfa

STRONG = "correct-horse-battery"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "mfa_req.duckdb")
    from app.main import app

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def enrol(client, token):
    """Complete enrolment for whoever holds this token."""
    secret = client.post("/api/auth/mfa/setup", headers=auth(token)).json()["secret"]
    client.post("/api/auth/mfa/enable", json={"code": mfa.generate(secret)}, headers=auth(token))
    return secret


@pytest.fixture()
def env(client):
    admin = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": STRONG, "workspace_name": "Acme",
    }).json()["access_token"]
    client.post("/api/members", json={"email": "mem@example.com", "role": "editor",
                                      "password": STRONG}, headers=auth(admin))
    member = client.post("/api/auth/login", json={
        "email": "mem@example.com", "password": STRONG}).json()["access_token"]
    return {"client": client, "admin": admin, "member": member}


def require_mfa(env):
    """Admin enrols, then switches the requirement on. Returns a fresh admin
    token, since enrolling does not change the session but re-reading is what a
    real client would do."""
    enrol(env["client"], env["admin"])
    r = env["client"].put("/api/workspace/security", json={"require_mfa": True},
                          headers=auth(env["admin"]))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- default ----

def test_off_by_default(env):
    body = env["client"].get("/api/workspace/security", headers=auth(env["admin"])).json()
    assert body["require_mfa"] is False
    assert body["members"] == 2 and body["members_with_mfa"] == 0


def test_only_admins_see_or_change_it(env):
    c = env["client"]
    assert c.get("/api/workspace/security", headers=auth(env["member"])).status_code == 403
    assert c.put("/api/workspace/security", json={"require_mfa": True},
                 headers=auth(env["member"])).status_code == 403


# ---------------------------------------------------------- enabling -----

def test_an_admin_must_enrol_before_requiring_it(env):
    """Proves the flow works before it is imposed on everyone else."""
    r = env["client"].put("/api/workspace/security", json={"require_mfa": True},
                          headers=auth(env["admin"]))
    assert r.status_code == 400
    assert "your own account first" in r.json()["detail"]


def test_an_enrolled_admin_can_require_it(env):
    body = require_mfa(env)
    assert body["require_mfa"] is True
    assert body["members_with_mfa"] == 1


# -------------------------------------------------------- enforcement ----

def test_a_member_without_a_factor_is_held_out(env):
    require_mfa(env)
    r = env["client"].get("/api/datasets", headers=auth(env["member"]))
    assert r.status_code == 403
    assert "mfa_setup_required" in r.json()["detail"]


def test_the_compliant_admin_is_unaffected(env):
    require_mfa(env)
    assert env["client"].get("/api/datasets", headers=auth(env["admin"])).status_code == 200


def test_enforcement_covers_endpoints_nobody_thought_about(env):
    """It is enforced in get_principal, so a new endpoint is covered by default
    rather than by someone remembering to add a check."""
    require_mfa(env)
    for path in ("/api/datasets", "/api/members", "/api/billing", "/api/templates",
                 "/api/privacy/export/me"):
        r = env["client"].get(path, headers=auth(env["member"]))
        assert r.status_code == 403, f"{path} was reachable without a second factor"


# ------------------------------------------------------- no lockout ------

def test_a_held_out_member_can_still_reach_setup(env):
    """The whole risk in this feature: a requirement that cannot be satisfied
    because satisfying it needs the access being withheld."""
    require_mfa(env)
    c = env["client"]
    assert c.get("/api/auth/mfa", headers=auth(env["member"])).status_code == 200
    assert c.post("/api/auth/mfa/setup", headers=auth(env["member"])).status_code == 200


def test_enrolling_restores_full_access(env):
    require_mfa(env)
    c = env["client"]
    assert c.get("/api/datasets", headers=auth(env["member"])).status_code == 403

    enrol(c, env["member"])
    assert c.get("/api/datasets", headers=auth(env["member"])).status_code == 200


def test_a_held_out_member_can_still_sign_out(env):
    """Being unable to end your own session while locked out would be its own
    small trap."""
    require_mfa(env)
    assert env["client"].post("/api/auth/revoke-sessions",
                              headers=auth(env["member"])).status_code == 200


def test_login_still_works_so_enrolment_is_reachable(env):
    """Held out is not signed out — the member must be able to get a token in
    order to enrol at all."""
    require_mfa(env)
    r = env["client"].post("/api/auth/login", json={
        "email": "mem@example.com", "password": STRONG})
    assert r.status_code == 200 and r.json()["access_token"]


# -------------------------------------------------------- turning off ----

def test_turning_it_off_restores_access_without_enrolment(env):
    require_mfa(env)
    c = env["client"]
    assert c.get("/api/datasets", headers=auth(env["member"])).status_code == 403

    c.put("/api/workspace/security", json={"require_mfa": False}, headers=auth(env["admin"]))
    assert c.get("/api/datasets", headers=auth(env["member"])).status_code == 200


def test_turning_it_off_does_not_require_being_enrolled(env):
    """Relaxing a control must never be harder than tightening it, or an admin
    who loses their phone cannot recover the workspace."""
    require_mfa(env)
    r = env["client"].put("/api/workspace/security", json={"require_mfa": False},
                          headers=auth(env["admin"]))
    assert r.status_code == 200 and r.json()["require_mfa"] is False


def test_the_requirement_does_not_leak_across_workspaces(env, client):
    require_mfa(env)
    other = client.post("/api/auth/signup", json={
        "email": "other@example.com", "password": STRONG, "workspace_name": "Other Co",
    }).json()["access_token"]
    assert client.get("/api/datasets", headers=auth(other)).status_code == 200
