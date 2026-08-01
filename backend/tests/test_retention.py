"""Retention.

This is the only code in the product that deletes customer data with nobody
watching, so the tests lean hard on what must NOT happen: nothing expires
unless configured, a mistyped period is refused, a preview never deletes, and a
sweep never reaches another tenant.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import retention

STRONG = "correct-horse-battery"
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "retention.duckdb")
    from app.main import app

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(con, workspace_id="ws_a", days_old=400):
    """A workspace with an old audit entry and an old dataset."""
    old = (NOW - timedelta(days=days_old)).replace(tzinfo=None)
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)",
                [workspace_id, workspace_id])
    con.execute("INSERT INTO audit_log (ts, workspace_id, user_id, action, detail) "
                "VALUES (?, ?, 'u1', 'upload', 'old.csv')", [old, workspace_id])
    con.execute("INSERT INTO audit_log (workspace_id, user_id, action, detail) "
                "VALUES (?, 'u1', 'upload', 'recent.csv')", [workspace_id])
    # ids are per-workspace so seeding two tenants cannot collide on the key
    con.execute("INSERT INTO datasets (dataset_id, workspace_id, name, source_file, kind, "
                "table_name, ingested_at) VALUES (?, ?, 'Old', 'o.csv', 'structured', NULL, ?)",
                [f"ds_old_{workspace_id}", workspace_id, old])
    con.execute("INSERT INTO datasets (dataset_id, workspace_id, name, source_file, kind) "
                "VALUES (?, ?, 'New', 'n.csv', 'structured')",
                [f"ds_new_{workspace_id}", workspace_id])


# --------------------------------------------------------- validation ----

def test_everything_is_off_by_default(con):
    policy = retention.get_policy(con, "ws_never_configured")
    assert policy.audit_days == policy.archive_days == policy.dataset_days == 0


def test_zero_means_keep_forever(con):
    _seed(con)
    assert retention.sweep(con, "ws_a", now=NOW) == {
        "audit_entries": 0, "archived_rows": 0, "datasets": []}
    assert con.execute("SELECT count(*) FROM audit_log WHERE workspace_id = 'ws_a'").fetchone()[0] == 2


@pytest.mark.parametrize("days", [1, 3, 6])
def test_a_mistyped_short_period_is_refused(days):
    """A fat-fingered "1" must not erase a year of history the same night."""
    with pytest.raises(retention.RetentionError):
        retention.validate_policy(audit_days=days)


def test_uploaded_data_has_a_higher_floor():
    retention.validate_policy(audit_days=retention.MIN_DAYS)          # fine
    with pytest.raises(retention.RetentionError):
        retention.validate_policy(dataset_days=retention.MIN_DAYS)    # too short for data


def test_negative_and_nonsense_periods_are_refused():
    for bad in (-1, "soon", None, 1.5e400):
        with pytest.raises(retention.RetentionError):
            retention.validate_policy(audit_days=bad)


def test_a_valid_policy_round_trips(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    saved = retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=90))
    assert saved.audit_days == 90
    assert retention.get_policy(con, "ws_a").audit_days == 90


# ------------------------------------------------------------ sweeping ---

def test_preview_reports_without_deleting(con):
    _seed(con)
    retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=30, dataset_days=90))

    report = retention.preview(con, "ws_a", now=NOW)
    assert report["audit_entries"] == 1
    assert [d["dataset_id"] for d in report["datasets"]] == ["ds_old_ws_a"]
    # nothing actually went away
    assert con.execute("SELECT count(*) FROM audit_log WHERE workspace_id = 'ws_a'").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM datasets WHERE workspace_id = 'ws_a'").fetchone()[0] == 2


def test_sweep_removes_only_what_aged_out(con):
    _seed(con)
    retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=30, dataset_days=90))

    removed = retention.sweep(con, "ws_a", now=NOW)
    assert removed["audit_entries"] == 1
    assert [d["dataset_id"] for d in removed["datasets"]] == ["ds_old_ws_a"]

    remaining = [r[0] for r in con.execute(
        "SELECT dataset_id FROM datasets WHERE workspace_id = 'ws_a'").fetchall()]
    assert remaining == ["ds_new_ws_a"]


def test_sweep_is_idempotent(con):
    _seed(con)
    retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=30, dataset_days=90))
    retention.sweep(con, "ws_a", now=NOW)
    second = retention.sweep(con, "ws_a", now=NOW)
    assert second["audit_entries"] == 0 and second["datasets"] == []


def test_the_sweep_records_itself_before_pruning_the_audit_log(con):
    """A sweep that prunes audit entries must not erase its own trace."""
    _seed(con)
    retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=30))
    retention.sweep(con, "ws_a", now=NOW)

    actions = [r[0] for r in con.execute(
        "SELECT action FROM audit_log WHERE workspace_id = 'ws_a'").fetchall()]
    assert "retention_sweep" in actions


def test_a_sweep_never_reaches_another_tenant(con):
    _seed(con, "ws_a")
    _seed(con, "ws_b")
    retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=30, dataset_days=90))

    retention.sweep(con, "ws_a", now=NOW)
    assert con.execute("SELECT count(*) FROM datasets WHERE workspace_id = 'ws_b'").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM audit_log WHERE workspace_id = 'ws_b'").fetchone()[0] == 2


def test_sweep_all_skips_unconfigured_workspaces(con):
    _seed(con, "ws_a")
    _seed(con, "ws_b")
    retention.set_policy(con, "ws_a", retention.validate_policy(audit_days=30))

    results = retention.sweep_all(con, now=NOW)
    assert set(results) == {"ws_a"}, "an unconfigured workspace must never be touched"


def test_one_bad_workspace_does_not_stop_the_others(con, monkeypatch):
    _seed(con, "ws_a")
    _seed(con, "ws_b")
    for wsid in ("ws_a", "ws_b"):
        retention.set_policy(con, wsid, retention.validate_policy(audit_days=30))

    real = retention.sweep

    def explode(c, workspace_id, *args, **kwargs):
        if workspace_id == "ws_a":
            raise RuntimeError("disk on fire")
        return real(c, workspace_id, *args, **kwargs)

    monkeypatch.setattr(retention, "sweep", explode)
    results = retention.sweep_all(con, now=NOW)
    assert "error" in results["ws_a"]
    assert results["ws_b"]["audit_entries"] == 1


# ----------------------------------------------------------- endpoints ---

@pytest.fixture()
def env(client):
    token = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": STRONG, "workspace_name": "Acme",
    }).json()["access_token"]
    client.post("/api/members", json={"email": "mem@example.com", "role": "editor",
                                      "password": STRONG}, headers=auth(token))
    member = client.post("/api/auth/login", json={
        "email": "mem@example.com", "password": STRONG}).json()["access_token"]
    return {"client": client, "admin": token, "member": member}


def test_retention_defaults_to_off_over_the_api(env):
    body = env["client"].get("/api/privacy/retention", headers=auth(env["admin"])).json()
    assert body["audit_days"] == body["archive_days"] == body["dataset_days"] == 0
    assert body["minimum_dataset_days"] > body["minimum_days"]


def test_only_admins_manage_retention(env):
    c = env["client"]
    assert c.get("/api/privacy/retention", headers=auth(env["member"])).status_code == 403
    assert c.put("/api/privacy/retention", json={"audit_days": 90},
                 headers=auth(env["member"])).status_code == 403


def test_the_api_refuses_a_dangerous_period(env):
    r = env["client"].put("/api/privacy/retention", json={"audit_days": 1},
                          headers=auth(env["admin"]))
    assert r.status_code == 400
    assert "at least" in r.json()["detail"]


def test_preview_does_not_persist_the_proposed_policy(env):
    """Previewing a policy must not arm it."""
    c = env["client"]
    assert c.post("/api/privacy/retention/preview", json={"audit_days": 30},
                  headers=auth(env["admin"])).status_code == 200
    assert c.get("/api/privacy/retention", headers=auth(env["admin"])).json()["audit_days"] == 0


def test_setting_and_running_retention(env):
    c = env["client"]
    assert c.put("/api/privacy/retention", json={"audit_days": 30},
                 headers=auth(env["admin"])).json()["audit_days"] == 30
    r = c.post("/api/privacy/retention/run", headers=auth(env["admin"]))
    assert r.status_code == 200 and "audit_entries" in r.json()
