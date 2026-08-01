"""Two-factor authentication.

The first test is the important one: TOTP is implemented on the standard
library rather than pulled from a package, so it is checked against the vectors
published in RFC 6238 itself. That verifies the implementation against the
specification rather than against our own assumptions.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from app.core import mfa

STRONG = "correct-horse-battery"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "mfa.duckdb")
    from app.main import app

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def user(client):
    token = client.post("/api/auth/signup", json={
        "email": "mfa@example.com", "password": STRONG, "workspace_name": "Acme",
    }).json()["access_token"]
    return {"client": client, "token": token, "email": "mfa@example.com"}


def enrol(user):
    """Complete enrolment; return (secret, recovery_codes)."""
    c, token = user["client"], user["token"]
    secret = c.post("/api/auth/mfa/setup", headers=auth(token)).json()["secret"]
    body = c.post("/api/auth/mfa/enable", json={"code": mfa.generate(secret)},
                  headers=auth(token)).json()
    return secret, body["recovery_codes"]


# ------------------------------------------------------- the standard -----

# RFC 6238 Appendix B, SHA-1 rows. Seed is the ASCII string below.
_RFC_SEED = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.mark.parametrize("unix_time,expected", [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
])
def test_matches_rfc6238_vectors(unix_time, expected):
    """Implementation checked against the specification, not against us."""
    step = unix_time // mfa.STEP_SECONDS
    assert mfa.code_at(_RFC_SEED, step, digits=8) == expected


def test_generated_codes_are_six_digits():
    code = mfa.generate(mfa.new_secret())
    assert len(code) == mfa.DIGITS and code.isdigit()


def test_secret_is_valid_base32_for_authenticator_apps():
    secret = mfa.new_secret()
    base64.b32decode(secret + "=" * (-len(secret) % 8))     # must not raise


def test_provisioning_uri_carries_what_an_app_needs():
    uri = mfa.provisioning_uri("JBSWY3DPEHPK3PXP", "a@b.com")
    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri and "issuer=InsightHub" in uri


# ---------------------------------------------------------- verifying -----

def test_accepts_a_code_from_the_neighbouring_step():
    """Phone clocks drift and people type slowly."""
    secret = mfa.new_secret()
    now = 1_700_000_000
    previous = mfa.code_at(secret, mfa.current_step(now) - 1)
    assert mfa.verify(secret, previous, at=now)


def test_rejects_a_code_from_far_away():
    secret = mfa.new_secret()
    now = 1_700_000_000
    stale = mfa.code_at(secret, mfa.current_step(now) - 10)
    with pytest.raises(mfa.MfaError):
        mfa.verify(secret, stale, at=now)


def test_rejects_a_replayed_code():
    """A code stays valid for its whole window, so one glimpsed over a
    shoulder could otherwise be reused seconds later."""
    secret = mfa.new_secret()
    now = 1_700_000_000
    code = mfa.generate(secret, at=now)
    step = mfa.verify(secret, code, at=now)
    with pytest.raises(mfa.MfaError):
        mfa.verify(secret, code, at=now, last_used_step=step)


@pytest.mark.parametrize("bad", ["", "abcdef", "12345", "1234567", None])
def test_malformed_codes_are_rejected(bad):
    with pytest.raises(mfa.MfaError):
        mfa.verify(mfa.new_secret(), bad)


def test_recovery_codes_are_hashed_not_stored_plainly():
    code = mfa.new_recovery_codes(1)[0]
    stored = mfa.hash_recovery_code(code)
    assert code not in stored
    assert mfa.recovery_matches(code, stored)
    assert not mfa.recovery_matches("wrong-code-here", stored)


# ------------------------------------------------------------ endpoints ---

def test_setup_does_not_switch_it_on(user):
    """A half-finished enrolment must never lock anyone out."""
    c, token = user["client"], user["token"]
    c.post("/api/auth/mfa/setup", headers=auth(token))
    assert c.get("/api/auth/mfa", headers=auth(token)).json()["enabled"] is False
    # password alone still logs in
    assert c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG}).status_code == 200


def test_enable_requires_a_valid_code(user):
    c, token = user["client"], user["token"]
    c.post("/api/auth/mfa/setup", headers=auth(token))
    assert c.post("/api/auth/mfa/enable", json={"code": "000000"},
                  headers=auth(token)).status_code == 400


def test_login_requires_the_code_once_enabled(user):
    c = user["client"]
    secret, _ = enrol(user)

    without = c.post("/api/auth/login", json={"email": user["email"], "password": STRONG})
    assert without.status_code == 401
    assert "mfa_required" in without.json()["detail"]

    # Enrolment spent the current step, so the *next* step's code is what a
    # real user's app would be showing by the time they log in again.
    next_code = mfa.code_at(secret, mfa.current_step() + 1)
    with_code = c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG, "mfa_code": next_code})
    assert with_code.status_code == 200 and with_code.json()["access_token"]


def test_reusing_the_enrolment_code_says_so_clearly(user):
    """Telling someone their valid code is "invalid email or password" sends
    them to reinstall their authenticator app. Say what actually happened."""
    c = user["client"]
    secret, _ = enrol(user)
    r = c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG, "mfa_code": mfa.generate(secret)})
    assert r.status_code == 401
    assert "already been used" in r.json()["detail"]


def test_a_wrong_code_does_not_log_in(user):
    c = user["client"]
    enrol(user)
    assert c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG, "mfa_code": "000000"}).status_code == 401


def test_a_recovery_code_works_and_is_single_use(user):
    c = user["client"]
    _, codes = enrol(user)
    first = codes[0]

    ok = c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG, "mfa_code": first})
    assert ok.status_code == 200

    again = c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG, "mfa_code": first})
    assert again.status_code == 401, "a recovery code must not work twice"


def test_recovery_codes_are_counted_down(user):
    c, token = user["client"], user["token"]
    _, codes = enrol(user)
    assert c.get("/api/auth/mfa", headers=auth(token)).json()["recovery_codes_remaining"] == len(codes)

    c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG, "mfa_code": codes[0]})
    assert c.get("/api/auth/mfa", headers=auth(token)).json()["recovery_codes_remaining"] == len(codes) - 1


def test_disabling_requires_the_password(user):
    """A stolen session must not be able to quietly remove the factor."""
    c, token = user["client"], user["token"]
    enrol(user)
    assert c.post("/api/auth/mfa/disable", json={"password": "not-the-password"},
                  headers=auth(token)).status_code == 401
    assert c.post("/api/auth/mfa/disable", json={"password": STRONG},
                  headers=auth(token)).status_code == 200
    # and the factor is genuinely gone
    assert c.post("/api/auth/login", json={
        "email": user["email"], "password": STRONG}).status_code == 200


def test_disabling_clears_the_recovery_codes(user):
    c, token = user["client"], user["token"]
    _, codes = enrol(user)
    c.post("/api/auth/mfa/disable", json={"password": STRONG}, headers=auth(token))
    assert c.get("/api/auth/mfa", headers=auth(token)).json()["recovery_codes_remaining"] == 0
