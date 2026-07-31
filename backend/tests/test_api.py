"""End-to-end API tests with real JWTs: auth, upload, dashboard, and the
cross-tenant rejection at the HTTP layer."""

import csv
import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api_test.duckdb")
    from app.main import app

    return TestClient(app)


def csv_upload(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return ("sales.csv", buf.getvalue().encode(), "text/csv")


SALES = [["date", "branch", "revenue"], ["2025-01-01", "Delhi", "1000"], ["2025-01-02", "Mumbai", "2000"]]


def signup(client, email, ws="Acme"):
    r = client.post("/api/auth/signup", json={"email": email, "password": "supersecret1", "workspace_name": ws})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_login_and_duplicate(client):
    token = signup(client, "a@example.com")
    assert token
    dup = client.post("/api/auth/signup",
                      json={"email": "a@example.com", "password": "supersecret1", "workspace_name": "X"})
    assert dup.status_code == 409
    login = client.post("/api/auth/login", json={"email": "a@example.com", "password": "supersecret1"})
    assert login.status_code == 200
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong"}).status_code == 401


def test_endpoints_require_auth(client):
    assert client.get("/api/datasets").status_code == 401
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 401


def test_full_flow_upload_dashboard_ask(client):
    token = signup(client, "b@example.com")
    up = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)}, headers=auth(token))
    assert up.status_code == 200, up.text
    ds_id = up.json()["dataset_id"]

    dash = client.get(f"/api/datasets/{ds_id}/dashboard", headers=auth(token))
    assert dash.status_code == 200
    revenue = next(k for k in dash.json()["kpis"] if k["column"] == "revenue")
    assert revenue["total"] == 3000


def test_cross_tenant_dataset_access_is_404(client):
    token_a = signup(client, "tenant-a@example.com", ws="A")
    token_b = signup(client, "tenant-b@example.com", ws="B")
    up = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)}, headers=auth(token_a))
    ds_id = up.json()["dataset_id"]

    # tenant B, with a valid token, cannot see tenant A's dataset
    assert client.get(f"/api/datasets/{ds_id}/dashboard", headers=auth(token_b)).status_code == 404
    assert client.get(f"/api/datasets/{ds_id}/schema", headers=auth(token_b)).status_code == 404
    # B's dataset list is empty; A's is not
    assert client.get("/api/datasets", headers=auth(token_b)).json() == []
    assert len(client.get("/api/datasets", headers=auth(token_a)).json()) == 1


def test_upload_rejects_unsupported_type(client):
    token = signup(client, "c@example.com")
    bad = ("evil.exe", b"MZ\x00\x00", "application/octet-stream")
    r = client.post("/api/datasets/upload", files={"file": bad}, headers=auth(token))
    assert r.status_code == 400


# ----------------------------------------------------- live sources -------

def test_sources_require_auth(client):
    assert client.get("/api/sources").status_code == 401
    assert client.post("/api/sources", json={"name": "x", "url": "https://x/a.csv"}).status_code == 401


def test_source_ssrf_rejected_at_api(client):
    token = signup(client, "ssrf@example.com")
    r = client.post("/api/sources",
                    json={"name": "internal", "kind": "url_csv", "url": "http://169.254.169.254/latest/"},
                    headers=auth(token))
    assert r.status_code == 400  # SSRF guard refuses the metadata endpoint


def test_source_create_sync_list_delete(client, tmp_path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.core import config
    monkeypatch.setattr(config, "ALLOW_PRIVATE_FETCH", True)  # local test server on loopback

    body = b"date,branch,revenue\n2025-01-01,Delhi,1000\n2025-01-02,Mumbai,2000\n"

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _, port = server.server_address
    url = f"http://127.0.0.1:{port}/data.csv"
    try:
        token = signup(client, "src@example.com")
        created = client.post("/api/sources",
                              json={"name": "Sales", "kind": "url_csv", "url": url, "refresh_interval_minutes": 0},
                              headers=auth(token))
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["sync"]["status"] == "ok"
        ds_id = payload["sync"]["dataset_id"]

        # the synced dataset drives a real dashboard
        dash = client.get(f"/api/datasets/{ds_id}/dashboard", headers=auth(token))
        assert dash.status_code == 200
        assert next(k for k in dash.json()["kpis"] if k["column"] == "revenue")["total"] == 3000

        src_id = payload["source"]["source_id"]
        assert client.post(f"/api/sources/{src_id}/sync", headers=auth(token)).status_code == 200
        assert any(s["source_id"] == src_id for s in client.get("/api/sources", headers=auth(token)).json())
        assert client.delete(f"/api/sources/{src_id}", headers=auth(token)).status_code == 200
        assert client.get("/api/sources", headers=auth(token)).json() == []
    finally:
        server.shutdown()


# ----------------------------------------------------- saved views --------

def test_views_crud_and_default(client):
    token = signup(client, "views@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]

    cfg = {"filters": {"branch": "Delhi"}, "measure": "revenue", "hidden_sections": ["treemap"]}
    created = client.post(f"/api/datasets/{ds_id}/views",
                          json={"name": "Delhi", "config": cfg, "make_default": True}, headers=auth(token))
    assert created.status_code == 200, created.text
    view = created.json()
    assert view["is_default"] and view["config"]["filters"] == {"branch": "Delhi"}

    listed = client.get(f"/api/datasets/{ds_id}/views", headers=auth(token)).json()
    assert len(listed) == 1

    patched = client.patch(f"/api/views/{view['view_id']}", json={"name": "Delhi FY"}, headers=auth(token))
    assert patched.status_code == 200 and patched.json()["name"] == "Delhi FY"

    assert client.delete(f"/api/views/{view['view_id']}", headers=auth(token)).status_code == 200
    assert client.get(f"/api/datasets/{ds_id}/views", headers=auth(token)).json() == []


def test_views_require_auth_and_reject_bad_section(client):
    assert client.get("/api/datasets/x/views").status_code == 401
    token = signup(client, "v2@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]
    bad = client.post(f"/api/datasets/{ds_id}/views",
                      json={"name": "x", "config": {"hidden_sections": ["nope"]}}, headers=auth(token))
    assert bad.status_code == 400


def test_view_cross_tenant_is_scoped(client):
    ta = signup(client, "va@example.com", ws="A")
    tb = signup(client, "vb@example.com", ws="B")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(ta)).json()["dataset_id"]
    view_id = client.post(f"/api/datasets/{ds_id}/views",
                          json={"name": "A view", "config": {}}, headers=auth(ta)).json()["view_id"]
    # B cannot see A's dataset views, nor edit/delete A's view
    assert client.get(f"/api/datasets/{ds_id}/views", headers=auth(tb)).json() == []
    assert client.patch(f"/api/views/{view_id}", json={"name": "hijack"}, headers=auth(tb)).status_code == 404
    assert client.delete(f"/api/views/{view_id}", headers=auth(tb)).status_code == 404


# --------------------------------------------------- public share links ---

def test_share_link_public_read_and_revoke(client):
    token = signup(client, "share@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]

    created = client.post(f"/api/datasets/{ds_id}/shares", json={"label": "Q1"}, headers=auth(token))
    assert created.status_code == 200, created.text
    share_token = created.json()["token"]

    # the public endpoint needs NO auth and returns the real dashboard
    pub = client.get(f"/api/public/{share_token}/dashboard")
    assert pub.status_code == 200
    kpis = pub.json()["dashboard"]["kpis"]
    assert next(k for k in kpis if k["column"] == "revenue")["total"] == 3000

    # once revoked, the public link 404s
    assert client.delete(f"/api/shares/{share_token}", headers=auth(token)).status_code == 200
    assert client.get(f"/api/public/{share_token}/dashboard").status_code == 404


def test_share_endpoints_require_auth_and_bad_token_404(client):
    assert client.post("/api/datasets/x/shares", json={}).status_code == 401
    assert client.get("/api/datasets/x/shares").status_code == 401
    # a random public token is just not found (no auth needed to probe)
    assert client.get("/api/public/not-a-real-token/dashboard").status_code == 404


def test_share_cross_tenant_revoke_scoped(client):
    ta = signup(client, "sa@example.com", ws="A")
    tb = signup(client, "sb@example.com", ws="B")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(ta)).json()["dataset_id"]
    stoken = client.post(f"/api/datasets/{ds_id}/shares", json={}, headers=auth(ta)).json()["token"]
    # B cannot revoke A's link, and the link keeps working
    assert client.delete(f"/api/shares/{stoken}", headers=auth(tb)).status_code == 404
    assert client.get(f"/api/public/{stoken}/dashboard").status_code == 200


# ------------------------------------------------- threshold alerts -------

def test_alerts_require_auth_and_reject_private_webhook(client):
    assert client.get("/api/datasets/x/alerts").status_code == 401
    token = signup(client, "al@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]
    bad = client.post(f"/api/datasets/{ds_id}/alerts",
                      json={"name": "x", "measure": "revenue", "aggregate": "total",
                            "op": "gt", "threshold": 0, "webhook_url": "http://127.0.0.1/hook"},
                      headers=auth(token))
    assert bad.status_code == 400  # SSRF guard refuses loopback webhook


def test_alert_crud_and_test_delivery(client, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.core import config
    monkeypatch.setattr(config, "ALLOW_PRIVATE_FETCH", True)

    posts = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            posts.append(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _, port = server.server_address
    url = f"http://127.0.0.1:{port}/hook"
    try:
        token = signup(client, "al2@example.com")
        ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                            headers=auth(token)).json()["dataset_id"]
        created = client.post(f"/api/datasets/{ds_id}/alerts",
                              json={"name": "Any revenue", "measure": "revenue", "aggregate": "total",
                                    "op": "gt", "threshold": 0, "webhook_url": url}, headers=auth(token))
        assert created.status_code == 200, created.text
        alert_id = created.json()["alert_id"]

        assert len(client.get(f"/api/datasets/{ds_id}/alerts", headers=auth(token)).json()) == 1
        assert client.post(f"/api/alerts/{alert_id}/test", headers=auth(token)).status_code == 200
        assert len(posts) == 1  # the test payload reached the webhook
        assert client.patch(f"/api/alerts/{alert_id}", json={"enabled": False}, headers=auth(token)).status_code == 200
        assert client.delete(f"/api/alerts/{alert_id}", headers=auth(token)).status_code == 200
    finally:
        server.shutdown()


# --------------------------------------------------- certified metrics ----

def test_metrics_crud_and_show_sql(client):
    token = signup(client, "metric@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]

    created = client.post(f"/api/datasets/{ds_id}/metrics",
                          json={"name": "Revenue", "kind": "aggregate",
                                "definition": {"agg": "sum", "column": "revenue"}, "format": "currency"},
                          headers=auth(token))
    assert created.status_code == 200, created.text
    metrics = created.json()
    assert metrics[0]["value"] == 3000.0 and 'sum("revenue")' in metrics[0]["sql"]

    listed = client.get(f"/api/datasets/{ds_id}/metrics", headers=auth(token)).json()
    assert len(listed) == 1
    assert client.delete(f"/api/metrics/{listed[0]['metric_id']}", headers=auth(token)).status_code == 200
    assert client.get(f"/api/datasets/{ds_id}/metrics", headers=auth(token)).json() == []


def test_metrics_require_auth_and_reject_bad_column(client):
    assert client.get("/api/datasets/x/metrics").status_code == 401
    token = signup(client, "m2@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]
    bad = client.post(f"/api/datasets/{ds_id}/metrics",
                      json={"name": "x", "kind": "aggregate", "definition": {"agg": "sum", "column": "evil"}},
                      headers=auth(token))
    assert bad.status_code == 400  # unknown column rejected


# ------------------------------------------------ team roles & members ----

def test_roles_enforced_across_endpoints(client):
    admin = signup(client, "owner@x.com", ws="X")
    assert client.post("/api/members", json={"email": "ed@x.com", "role": "editor", "password": "editorpass1"},
                       headers=auth(admin)).status_code == 200
    assert client.post("/api/members", json={"email": "vw@x.com", "role": "viewer", "password": "viewerpass1"},
                       headers=auth(admin)).status_code == 200
    ed = client.post("/api/auth/login", json={"email": "ed@x.com", "password": "editorpass1"}).json()
    vw = client.post("/api/auth/login", json={"email": "vw@x.com", "password": "viewerpass1"}).json()
    assert ed["role"] == "editor" and vw["role"] == "viewer"

    # editor can upload; viewer is read-only
    up = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)}, headers=auth(ed["access_token"]))
    assert up.status_code == 200
    ds_id = up.json()["dataset_id"]
    assert client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                       headers=auth(vw["access_token"])).status_code == 403

    # viewer can read the dashboard but not create content
    assert client.get(f"/api/datasets/{ds_id}/dashboard", headers=auth(vw["access_token"])).status_code == 200
    assert client.post(f"/api/datasets/{ds_id}/views", json={"name": "v", "config": {}},
                       headers=auth(vw["access_token"])).status_code == 403
    assert client.post(f"/api/datasets/{ds_id}/views", json={"name": "v", "config": {}},
                       headers=auth(ed["access_token"])).status_code == 200

    # team management is admin-only
    assert client.get("/api/members", headers=auth(ed["access_token"])).status_code == 403
    assert len(client.get("/api/members", headers=auth(admin)).json()) == 3


def test_last_admin_guard_and_password_change(client):
    admin = signup(client, "solo@x.com", ws="X")
    admin_id = client.get("/api/members", headers=auth(admin)).json()[0]["user_id"]
    # the only admin cannot be demoted
    assert client.patch(f"/api/members/{admin_id}", json={"role": "viewer"}, headers=auth(admin)).status_code == 400
    # change my password, then the new one works and the old one doesn't
    assert client.post("/api/auth/change-password",
                       json={"old_password": "supersecret1", "new_password": "brandnew12"},
                       headers=auth(admin)).status_code == 200
    assert client.post("/api/auth/login", json={"email": "solo@x.com", "password": "brandnew12"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "solo@x.com", "password": "supersecret1"}).status_code == 401


def test_member_endpoints_require_admin_auth(client):
    assert client.get("/api/members").status_code == 401
    assert client.post("/api/members", json={"email": "x@x.com", "role": "viewer"}).status_code == 401


# ---------------------------------------------- driver analysis -----------

def test_explain_endpoint(client):
    token = signup(client, "explain@example.com")
    ds_id = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                        headers=auth(token)).json()["dataset_id"]
    r = client.get(f"/api/datasets/{ds_id}/explain", headers=auth(token))
    assert r.status_code == 200 and "available" in r.json()   # single-month sample → available False, still 200
    assert client.get(f"/api/datasets/{ds_id}/explain").status_code == 401


# ---------------------------------------------- multi-table joins ---------

def _upload(client, token, name, rows):
    buf = io.StringIO(); csv.writer(buf).writerows(rows)
    files = {"file": (name, buf.getvalue().encode(), "text/csv")}
    return client.post("/api/datasets/upload", files=files, headers=auth(token)).json()["dataset_id"]


def test_join_flow(client):
    token = signup(client, "join@example.com")
    orders = _upload(client, token, "orders.csv",
                     [["order_id", "customer_id", "amount"], ["o1", "c1", "100"], ["o2", "c2", "200"]])
    customers = _upload(client, token, "customers.csv",
                        [["customer_id", "region"], ["c1", "North"], ["c2", "South"]])

    # suggest finds the shared key
    sug = client.get("/api/joins/suggest", params={"left": orders, "right": customers}, headers=auth(token))
    assert sug.status_code == 200 and sug.json()["suggested"]["left_key"] == "customer_id"

    # create the join → a new dataset
    created = client.post("/api/joins", headers=auth(token), json={
        "left_dataset_id": orders, "right_dataset_id": customers,
        "left_key": "customer_id", "right_key": "customer_id", "join_type": "left"})
    assert created.status_code == 200, created.text
    joined_ds = created.json()["dataset_id"]

    # the joined dataset has region + amount and drives a dashboard
    dash = client.get(f"/api/datasets/{joined_ds}/dashboard", headers=auth(token))
    assert dash.status_code == 200
    assert next(k for k in dash.json()["kpis"] if k["column"] == "amount")["total"] == 300

    listed = client.get("/api/joins", headers=auth(token)).json()
    assert len(listed) == 1 and listed[0]["dataset_id"] == joined_ds
    assert client.delete(f"/api/joins/{listed[0]['relation_id']}", headers=auth(token)).status_code == 200
    assert client.get("/api/joins", headers=auth(token)).json() == []


def test_join_requires_auth_and_rejects_bad_key(client):
    assert client.get("/api/joins").status_code == 401
    token = signup(client, "join2@example.com")
    a = _upload(client, token, "a.csv", [["k", "v"], ["1", "x"]])
    b = _upload(client, token, "b.csv", [["k", "w"], ["1", "y"]])
    bad = client.post("/api/joins", headers=auth(token), json={
        "left_dataset_id": a, "right_dataset_id": b,
        "left_key": "nope", "right_key": "k", "join_type": "left"})
    assert bad.status_code == 400


# ---------------------------------- sample data / CSV export / day filter --

def test_sample_dataset_builds_a_dashboard(client):
    token = signup(client, "sample@example.com")
    r = client.post("/api/datasets/sample", headers=auth(token))
    assert r.status_code == 200 and r.json()["row_count"] > 0
    dash = client.get(f"/api/datasets/{r.json()['dataset_id']}/dashboard", headers=auth(token))
    assert dash.status_code == 200 and len(dash.json()["kpis"]) >= 1


def test_csv_export_has_user_columns_only(client):
    token = signup(client, "csv@example.com")
    ds = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)}, headers=auth(token)).json()["dataset_id"]
    r = client.get(f"/api/datasets/{ds}/export.csv", headers=auth(token))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.text
    assert "revenue" in body and "_ih_batch" not in body   # provenance column excluded
    assert body.strip().count("\n") >= 2                    # header + 2 data rows


def test_day_level_date_filter(client):
    token = signup(client, "day@example.com")
    ds = _upload(client, token, "daily.csv", [
        ["date", "branch", "revenue"],
        ["2025-03-01", "A", "100"], ["2025-03-10", "A", "100"],
        ["2025-03-20", "A", "100"], ["2025-03-31", "A", "100"]])
    full = client.get(f"/api/datasets/{ds}/dashboard", headers=auth(token)).json()["row_count_filtered"]
    assert full == 4
    # 2025-03-05 .. 2025-03-15 (exclusive end → 03-16) → only the 10th qualifies
    narrowed = client.get(f"/api/datasets/{ds}/dashboard",
                          params={"date_from": "2025-03-05", "date_to": "2025-03-15"},
                          headers=auth(token)).json()["row_count_filtered"]
    assert narrowed == 1


# ---------------------------------------------------- billing / plans -----

def test_billing_quota_gating(client, monkeypatch):
    from app.core import config
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    token = signup(client, "bill@example.com")
    # free plan caps datasets at 2
    for _ in range(2):
        assert client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                           headers=auth(token)).status_code == 200
    third = client.post("/api/datasets/upload", files={"file": csv_upload(SALES)}, headers=auth(token))
    assert third.status_code == 402 and "upgrade" in third.json()["detail"].lower()

    ent = client.get("/api/billing", headers=auth(token)).json()
    assert ent["plan"] == "free" and ent["usage"]["datasets"] == 2

    # upgrading (manual/self-hosted) lifts the cap
    assert client.post("/api/billing/plan", json={"plan": "pro"}, headers=auth(token)).status_code == 200
    assert client.post("/api/datasets/upload", files={"file": csv_upload(SALES)},
                       headers=auth(token)).status_code == 200


def test_billing_webhook_upgrades(client):
    reg = client.post("/api/auth/signup",
                      json={"email": "wh@example.com", "password": "supersecret1", "workspace_name": "W"}).json()
    token, ws_id = reg["access_token"], reg["workspace_id"]
    event = {"type": "checkout.session.completed",
             "data": {"object": {"client_reference_id": ws_id, "subscription": "sub_x",
                                  "metadata": {"plan": "pro"}}}}
    assert client.post("/api/billing/webhook", json=event).status_code == 200
    assert client.get("/api/billing", headers=auth(token)).json()["subscription"]["plan"] == "pro"


def test_billing_endpoints_require_auth_and_admin(client):
    assert client.get("/api/billing").status_code == 401
    token = signup(client, "b3@example.com")  # admin
    assert client.get("/api/billing", headers=auth(token)).status_code == 200
    # unknown plan rejected
    assert client.post("/api/billing/plan", json={"plan": "enterprise"}, headers=auth(token)).status_code == 400
