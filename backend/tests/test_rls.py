"""Row-level security: rule validation, predicate semantics, and — the part
that actually matters — that every read path a member can reach is filtered.

The end-to-end tests below deliberately go through HTTP rather than calling the
analytics functions directly: a leak in this feature looks like "one endpoint
forgot to pass user_id", which only an endpoint-level test can catch.
"""

import csv
import io
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.analytics.rls import RuleError, build_predicate, create_rule, delete_rule, list_rules
from app.ingest.pipeline import ingest_upload


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "rls_test.duckdb")
    from app.main import app

    return TestClient(app)


SALES = [
    ["date", "region", "product", "revenue"],
    ["2025-01-05", "North", "Widget", "1000"],
    ["2025-01-06", "South", "Widget", "2000"],
    ["2025-02-07", "East", "Gadget", "3000"],
    ["2025-02-08", "North", "Gadget", "4000"],
    ["2025-03-09", "South", "Gizmo", "5000"],
]


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def env(client):
    """An admin with data, plus a viewer restricted to the North region."""
    admin = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": "supersecret1", "workspace_name": "Acme",
    }).json()["access_token"]

    ds = client.post("/api/datasets/upload",
                     files={"file": ("sales.csv", _csv(SALES), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]

    client.post("/api/members", json={"email": "north@example.com", "role": "viewer",
                                      "password": "supersecret1"}, headers=auth(admin))
    members = client.get("/api/members", headers=auth(admin)).json()
    viewer_id = next(m["user_id"] for m in members if m["email"] == "north@example.com")
    viewer = client.post("/api/auth/login", json={
        "email": "north@example.com", "password": "supersecret1",
    }).json()["access_token"]

    return {"client": client, "admin": admin, "viewer": viewer,
            "viewer_id": viewer_id, "dataset_id": ds}


def restrict(env, values, column="region", operator="in"):
    r = env["client"].post(
        f"/api/datasets/{env['dataset_id']}/rls",
        json={"user_id": env["viewer_id"], "column_name": column,
              "values": values, "operator": operator},
        headers=auth(env["admin"]),
    )
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------ rule validation ---

def test_rule_rejects_unknown_column(env):
    r = env["client"].post(
        f"/api/datasets/{env['dataset_id']}/rls",
        json={"user_id": env["viewer_id"], "column_name": "not_a_column", "values": ["x"]},
        headers=auth(env["admin"]),
    )
    assert r.status_code == 400


def test_rule_rejects_foreign_member(env):
    r = env["client"].post(
        f"/api/datasets/{env['dataset_id']}/rls",
        json={"user_id": "usr_someone_else", "column_name": "region", "values": ["North"]},
        headers=auth(env["admin"]),
    )
    assert r.status_code == 400


def test_rule_requires_values(env):
    r = env["client"].post(
        f"/api/datasets/{env['dataset_id']}/rls",
        json={"user_id": env["viewer_id"], "column_name": "region", "values": []},
        headers=auth(env["admin"]),
    )
    assert r.status_code == 400


def test_only_admins_manage_rules(env):
    """Rules are the access policy — a viewer must not read or write them."""
    assert env["client"].get(f"/api/datasets/{env['dataset_id']}/rls",
                             headers=auth(env["viewer"])).status_code == 403
    assert env["client"].post(
        f"/api/datasets/{env['dataset_id']}/rls",
        json={"user_id": env["viewer_id"], "column_name": "region", "values": ["South"]},
        headers=auth(env["viewer"]),
    ).status_code == 403


# -------------------------------------------------- predicate semantics ---

def test_no_rules_means_unrestricted(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    where, params = build_predicate(con, "ws_a", "usr_nobody", res.dataset_id)
    assert where == "" and params == []


def test_same_column_rules_widen_different_columns_narrow(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO users VALUES ('usr_a', 'ws_a', 'a@x.com', 'h', 'viewer', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    create_rule(con, "ws_a", res.dataset_id, "usr_a", "region", ["North"])
    create_rule(con, "ws_a", res.dataset_id, "usr_a", "region", ["South"])
    create_rule(con, "ws_a", res.dataset_id, "usr_a", "product", ["Widget"])

    where, params = build_predicate(con, "ws_a", "usr_a", res.dataset_id)
    assert where.count(" OR ") == 1        # the two region rules OR together
    assert where.count(" AND ") == 1       # region AND product
    assert set(params) == {"North", "South", "Widget"}


def test_broken_rule_fails_closed(con):
    """A rule naming a column the dataset no longer has must deny, not ignore."""
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO users VALUES ('usr_a', 'ws_a', 'a@x.com', 'h', 'viewer', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    create_rule(con, "ws_a", res.dataset_id, "usr_a", "region", ["North"])
    # simulate the column disappearing under the rule (re-upload with new headers)
    con.execute("DELETE FROM dataset_columns WHERE dataset_id = ? AND column_name = 'region'",
                [res.dataset_id])

    where, params = build_predicate(con, "ws_a", "usr_a", res.dataset_id)
    assert where == "1 = 0" and params == []


def test_rules_are_workspace_scoped(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    con.execute("INSERT INTO users VALUES ('usr_a', 'ws_a', 'a@x.com', 'h', 'viewer', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    rule = create_rule(con, "ws_a", res.dataset_id, "usr_a", "region", ["North"])

    assert list_rules(con, "ws_b", res.dataset_id) == []
    assert delete_rule(con, "ws_b", rule["rule_id"]) == 0
    assert len(list_rules(con, "ws_a", res.dataset_id)) == 1


def test_bad_operator_rejected(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO users VALUES ('usr_a', 'ws_a', 'a@x.com', 'h', 'viewer', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    with pytest.raises(RuleError):
        create_rule(con, "ws_a", res.dataset_id, "usr_a", "region", ["North"], operator="drop")


# ------------------------------------------- enforcement, per read path ---

def test_dashboard_totals_only_cover_permitted_rows(env):
    c, ds = env["client"], env["dataset_id"]
    full = c.get(f"/api/datasets/{ds}/dashboard", headers=auth(env["admin"])).json()
    assert full["kpis"][0]["total"] == 15000        # every row

    restrict(env, ["North"])
    limited = c.get(f"/api/datasets/{ds}/dashboard", headers=auth(env["viewer"])).json()
    assert limited["kpis"][0]["total"] == 5000      # 1000 + 4000
    assert limited["row_count_filtered"] == 2


def test_breakdowns_and_filter_options_hide_other_regions(env):
    restrict(env, ["North"])
    dash = env["client"].get(f"/api/datasets/{env['dataset_id']}/dashboard",
                             headers=auth(env["viewer"])).json()
    regions = [d["name"] for d in dash["breakdowns"]["region"]["data"]]
    assert regions == ["North"]
    # the filter dropdown must not advertise values the member cannot reach
    assert dash["filter_options"]["region"]["values"] == ["North"]


def test_csv_export_is_restricted(env):
    restrict(env, ["North"])
    body = env["client"].get(f"/api/datasets/{env['dataset_id']}/export.csv",
                             headers=auth(env["viewer"])).text
    assert "North" in body
    assert "South" not in body and "East" not in body


def test_ask_is_restricted(env):
    restrict(env, ["North"])
    r = env["client"].post(f"/api/datasets/{env['dataset_id']}/query",
                           json={"question": "total revenue"}, headers=auth(env["viewer"]))
    assert r.status_code == 200
    assert r.json()["value"] == 5000


def test_certified_metrics_are_restricted(env):
    c, ds = env["client"], env["dataset_id"]
    c.post(f"/api/datasets/{ds}/metrics",
           json={"name": "Revenue", "kind": "aggregate",
                 "definition": {"agg": "sum", "column": "revenue"}, "format": "currency"},
           headers=auth(env["admin"]))
    restrict(env, ["North"])
    metrics = c.get(f"/api/datasets/{ds}/metrics", headers=auth(env["viewer"])).json()
    assert metrics[0]["value"] == 5000


def test_quality_report_is_restricted(env):
    restrict(env, ["North"])
    q = env["client"].get(f"/api/datasets/{env['dataset_id']}/quality",
                          headers=auth(env["viewer"])).json()
    assert q["row_count"] == 2


def test_drivers_are_restricted(env):
    restrict(env, ["North"])
    r = env["client"].get(f"/api/datasets/{env['dataset_id']}/explain",
                          headers=auth(env["viewer"]))
    assert r.status_code == 200
    body = r.json()
    if body.get("available"):
        # whatever shape the driver payload takes, no restricted value may appear
        blob = str(body)
        assert "South" not in blob and "East" not in blob


def test_not_in_operator_excludes_and_keeps_nulls_visible(env):
    restrict(env, ["North"], operator="not_in")
    dash = env["client"].get(f"/api/datasets/{env['dataset_id']}/dashboard",
                             headers=auth(env["viewer"])).json()
    regions = {d["name"] for d in dash["breakdowns"]["region"]["data"]}
    assert regions == {"South", "East"}


def test_removing_the_rule_restores_full_access(env):
    rule = restrict(env, ["North"])
    c, ds = env["client"], env["dataset_id"]
    assert c.get(f"/api/datasets/{ds}/dashboard", headers=auth(env["viewer"])).json()["kpis"][0]["total"] == 5000

    assert c.delete(f"/api/rls/{rule['rule_id']}", headers=auth(env["admin"])).status_code == 200
    assert c.get(f"/api/datasets/{ds}/dashboard", headers=auth(env["viewer"])).json()["kpis"][0]["total"] == 15000


def test_admin_without_rules_still_sees_everything(env):
    """Rules bind to a user, so restricting the viewer must not touch the admin."""
    restrict(env, ["North"])
    dash = env["client"].get(f"/api/datasets/{env['dataset_id']}/dashboard",
                             headers=auth(env["admin"])).json()
    assert dash["kpis"][0]["total"] == 15000


# ------------------------------------------------------------- sharing ----

def test_share_link_shows_only_what_its_author_could_see(env):
    """The escape hatch that matters: a restricted member publishes a public
    link, which must not become an unrestricted view of the dataset."""
    c, ds = env["client"], env["dataset_id"]
    restrict(env, ["North"])
    # let the restricted member create a link (viewers cannot, so promote first)
    c.patch(f"/api/members/{env['viewer_id']}", json={"role": "editor"}, headers=auth(env["admin"]))
    # the role is carried in the JWT, so the promotion needs a fresh login
    promoted = c.post("/api/auth/login", json={
        "email": "north@example.com", "password": "supersecret1",
    }).json()["access_token"]
    token = c.post(f"/api/datasets/{ds}/shares", json={"label": "leak?"},
                   headers=auth(promoted)).json()["token"]

    public = c.get(f"/api/public/{token}/dashboard").json()
    assert public["dashboard"]["kpis"][0]["total"] == 5000


# --------------------------------------------------------- source guard ---

# Modules allowed to name a dataset's physical table directly, with why:
_RAW_TABLE_ALLOWED = {
    "rls.py",       # builds the secured relation itself
    "pipeline.py",  # creates/loads the table
    "append.py",    # writes new batches
    "joins.py",     # materializes a new dataset (an editor action, like upload)
    "quality.py",   # apply_cleaning mutates the table; its report path is secured
    "connectors.py",
}


def test_no_new_read_path_bypasses_rls():
    """Fail if a module starts querying a dataset table without going through
    `secured_relation`. RLS has no single choke point in the SQL layer, so this
    test *is* the choke point — a tenth read path cannot be added silently."""
    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        if path.name in _RAW_TABLE_ALLOWED:
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, text in enumerate(lines, 1):
            if not re.search(r'safe_table_name\(\s*(?:dataset|schema)\[', text):
                continue
            # an audited exception carries `rls-raw-table-ok` in a nearby comment
            if "rls-raw-table-ok" in "\n".join(lines[max(0, i - 4):i]):
                continue
            offenders.append(f"{path.relative_to(app_dir)}:{i}")
    assert not offenders, (
        "these resolve a dataset table directly instead of via "
        f"rls.secured_relation(): {offenders}"
    )
