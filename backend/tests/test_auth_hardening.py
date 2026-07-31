"""Password policy, session revocation, and login lockout.

These are the three items that appear on every enterprise security
questionnaire, and all three were missing: the policy was `len >= 8`, a JWT
could not be taken back, and an account could be guessed at indefinitely.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import passwords

GOOD = "correct-horse-battery"          # long, not common, not derived


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "auth_test.duckdb")
    from app.main import app

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def signup(client, email=None, password=GOOD, workspace="Acme"):
    return client.post("/api/auth/signup", json={
        "email": email or "boss@example.com", "password": password, "workspace_name": workspace,
    })


# ------------------------------------------------------ password policy ---

@pytest.mark.parametrize("password,reason", [
    ("short1", "too short"),
    ("password123", "top of every breach list"),
    ("Password123", "same, differently cased"),
    ("P@ssw0rd", "leetspeak is not a different password"),
    ("aaaaaaaaaaaa", "a single repeated character"),
    ("abcdefghijkl", "a sequential run"),
    ("1234567890", "a numeric run"),
])
def test_weak_passwords_are_refused(password, reason):
    with pytest.raises(passwords.WeakPassword):
        passwords.validate(password, email="someone@example.com")


@pytest.mark.parametrize("password", [
    GOOD, "a very long passphrase about tea", "Zx9!kdow2P-quiet", "मेरा-लंबा-पासवर्ड-यहाँ",
])
def test_reasonable_passwords_are_accepted(password):
    passwords.validate(password, email="someone@example.com")


def test_password_may_not_contain_the_account_identity():
    with pytest.raises(passwords.WeakPassword):
        passwords.validate("northwind-traders-2026", email="a@northwind.com",
                           workspace_name="Northwind Traders")


def test_password_length_is_capped_at_bcrypt_limit():
    """bcrypt silently truncates past 72 bytes; a user who typed 200
    characters should not be told a secret they did not get."""
    with pytest.raises(passwords.WeakPassword):
        passwords.validate("x" * 200, email="a@b.com")


def test_signup_enforces_the_policy(client):
    assert signup(client, password="password123").status_code == 400
    assert signup(client, password=GOOD).status_code == 200


def test_error_message_is_actionable(client):
    detail = signup(client, password="short1").json()["detail"]
    assert "10" in detail and "character" in detail


# ------------------------------------------------------------- lockout ----

def test_repeated_failures_lock_the_account(client):
    signup(client, email="target@example.com")
    for _ in range(8):
        r = client.post("/api/auth/login", json={"email": "target@example.com", "password": "wrong-guess-1"})
        assert r.status_code == 401
    # correct password, but the account is now locked
    blocked = client.post("/api/auth/login", json={"email": "target@example.com", "password": GOOD})
    assert blocked.status_code == 401


def test_a_successful_login_clears_the_counter(client):
    signup(client, email="ok@example.com")
    for _ in range(3):
        client.post("/api/auth/login", json={"email": "ok@example.com", "password": "wrong-guess-1"})
    assert client.post("/api/auth/login", json={"email": "ok@example.com", "password": GOOD}).status_code == 200
    # counter reset, so another 7 failures still must not lock
    for _ in range(7):
        client.post("/api/auth/login", json={"email": "ok@example.com", "password": "wrong-guess-1"})
    assert client.post("/api/auth/login", json={"email": "ok@example.com", "password": GOOD}).status_code == 200


def test_failures_do_not_reveal_whether_an_account_exists(client):
    signup(client, email="real@example.com")
    known = client.post("/api/auth/login", json={"email": "real@example.com", "password": "wrong-guess-1"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "wrong-guess-1"})
    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"] == unknown.json()["detail"]


# -------------------------------------------------- session revocation ----

def test_sign_out_everywhere_invalidates_existing_tokens(client):
    token = signup(client).json()["access_token"]
    assert client.get("/api/datasets", headers=auth(token)).status_code == 200

    assert client.post("/api/auth/revoke-sessions", headers=auth(token)).status_code == 200
    assert client.get("/api/datasets", headers=auth(token)).status_code == 401


def test_changing_a_password_ends_existing_sessions(client):
    """Otherwise 'someone knows my password' has no remedy."""
    token = signup(client).json()["access_token"]
    r = client.post("/api/auth/change-password",
                    json={"old_password": GOOD, "new_password": "a different long phrase"},
                    headers=auth(token))
    assert r.status_code == 200
    assert client.get("/api/datasets", headers=auth(token)).status_code == 401


def test_change_password_enforces_the_policy(client):
    token = signup(client).json()["access_token"]
    r = client.post("/api/auth/change-password",
                    json={"old_password": GOOD, "new_password": "password123"},
                    headers=auth(token))
    assert r.status_code == 400


def test_a_removed_member_loses_access_immediately(client):
    """A JWT outliving the account is the classic offboarding hole."""
    admin = signup(client).json()["access_token"]
    client.post("/api/members", json={"email": "temp@example.com", "role": "editor",
                                      "password": GOOD}, headers=auth(admin))
    member_token = client.post("/api/auth/login", json={
        "email": "temp@example.com", "password": GOOD}).json()["access_token"]
    assert client.get("/api/datasets", headers=auth(member_token)).status_code == 200

    user_id = next(m["user_id"] for m in client.get("/api/members", headers=auth(admin)).json()
                   if m["email"] == "temp@example.com")
    client.delete(f"/api/members/{user_id}", headers=auth(admin))

    assert client.get("/api/datasets", headers=auth(member_token)).status_code == 401


def test_a_demotion_applies_to_an_existing_token(client):
    """Role used to live only in the JWT, so a demoted editor kept editing
    until they happened to log in again."""
    admin = signup(client).json()["access_token"]
    client.post("/api/members", json={"email": "ed@example.com", "role": "editor",
                                      "password": GOOD}, headers=auth(admin))
    editor = client.post("/api/auth/login", json={
        "email": "ed@example.com", "password": GOOD}).json()["access_token"]
    user_id = next(m["user_id"] for m in client.get("/api/members", headers=auth(admin)).json()
                   if m["email"] == "ed@example.com")

    client.patch(f"/api/members/{user_id}", json={"role": "viewer"}, headers=auth(admin))
    # the old token is now invalid; the new session is a viewer
    assert client.get("/api/datasets", headers=auth(editor)).status_code == 401
    viewer = client.post("/api/auth/login", json={
        "email": "ed@example.com", "password": GOOD}).json()["access_token"]
    assert client.post("/api/datasets/sample", headers=auth(viewer)).status_code == 403
