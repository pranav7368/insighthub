"""Scheduled email reports: grounded content, masking, scheduling, and real
delivery over SMTP to a minimal in-process server."""

import csv
import email
import io
import json
import socketserver
import threading
from datetime import datetime
from email import policy

import pytest
from fastapi.testclient import TestClient

from app.analytics.reports import (
    ReportError, build_report, create_report, is_due, list_reports, run_due_reports, send_report,
)
from app.core import config
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SALES = [["date", "customer_name", "email", "region", "revenue"]] + [
    [f"2025-{m:02d}-{d:02d}", name, mail, region, str(rev)]
    for m in range(1, 7)
    for d, (name, mail, region, rev) in enumerate([
        ("Priya Sharma", "priya.sharma@acme.com", "North", 1000 + m * 50),
        ("Raj Patel", "raj.patel@corp.io", "South", 600 + m * 10),
        ("Anita Desai", "anita@example.org", "East", 300),
    ], start=3)
]
RAW = ["priya.sharma@acme.com", "Priya Sharma", "raj.patel@corp.io"]


# ------------------------------------------------- a tiny SMTP server ---

class _SMTP(socketserver.StreamRequestHandler):
    """Just enough SMTP for smtplib: greet, EHLO, MAIL, RCPT, DATA, QUIT."""

    def handle(self):
        self.wfile.write(b"220 sink ready\r\n")
        rcpts = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode().strip().upper()
            if cmd.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250 sink\r\n")
            elif cmd.startswith("MAIL FROM"):
                rcpts = []
                self.wfile.write(b"250 ok\r\n")
            elif cmd.startswith("RCPT TO"):
                rcpts.append(line.decode().split(":", 1)[1].strip().strip("<>"))
                self.wfile.write(b"250 ok\r\n")
            elif cmd == "DATA":
                self.wfile.write(b"354 go ahead\r\n")
                data = b""
                while not data.endswith(b"\r\n.\r\n"):
                    data += self.rfile.readline()
                self.server.messages.append((rcpts, email.message_from_bytes(data[:-5], policy=policy.default)))
                self.wfile.write(b"250 queued\r\n")
            elif cmd == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


@pytest.fixture()
def smtp(monkeypatch):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTP)
    server.daemon_threads = True
    server.messages = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "SMTP_PORT", server.server_address[1])
    monkeypatch.setattr(config, "SMTP_STARTTLS", False)
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "APP_URL", "https://app.example.com")
    yield server
    server.shutdown()


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'B')")
    dsid = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES)).dataset_id
    return con, "ws_a", dsid


def _body(msg, kind):
    return msg.get_body(preferencelist=(kind,)).get_content()


# ----------------------------------------------------------- content ---

def test_report_is_built_from_the_computed_numbers(ds):
    con, ws, dsid = ds
    r = build_report(con, ws, dsid, measure="revenue")
    # June: 1300 + 660 + 300 = 2260, May: 1250 + 650 + 300 = 2200
    assert "Revenue rose 2.7%" in r["subject"]
    assert any("Revenue: ₹" in k and "in Jun 2025" in k for k in r["facts"]["kpis"])
    # split by the dimension that best explains the move -- here a masked customer
    assert "P*****: +₹50" in r["text"] and "<li>" in r["html"]
    assert "computed directly from your data" in r["text"]


def test_reports_are_masked_even_for_an_admin_author(ds):
    """An email leaves the system: masked whoever built it (no user = system/admin)."""
    con, ws, dsid = ds
    r = build_report(con, ws, dsid, measure="revenue", user_id=None)
    blob = r["text"] + r["html"] + r["subject"]
    for raw in RAW:
        assert raw not in blob


# -------------------------------------------------------- scheduling ---

def test_due_rules():
    base = {"enabled": True, "last_status": "sent", "last_attempt_at": None}
    jan10 = datetime(2026, 1, 10, 9)
    assert is_due({**base, "frequency": "daily", "last_sent_at": None}, jan10)
    assert not is_due({**base, "frequency": "daily", "last_sent_at": "2026-01-10 06:00:00"}, jan10)
    assert is_due({**base, "frequency": "daily", "last_sent_at": "2026-01-09 23:00:00"}, jan10)
    assert not is_due({**base, "frequency": "weekly", "last_sent_at": "2026-01-04 09:00:00"}, jan10)
    assert is_due({**base, "frequency": "weekly", "last_sent_at": "2026-01-03 09:00:00"}, jan10)
    assert not is_due({**base, "frequency": "monthly", "last_sent_at": "2026-01-01 09:00:00"}, jan10)
    assert is_due({**base, "frequency": "monthly", "last_sent_at": "2025-12-31 09:00:00"}, jan10)
    assert not is_due({**base, "enabled": False, "frequency": "daily", "last_sent_at": None}, jan10)
    # a failed attempt waits an hour before retrying
    failed = {**base, "frequency": "daily", "last_sent_at": None, "last_status": "error"}
    assert not is_due({**failed, "last_attempt_at": "2026-01-10 08:30:00"}, jan10)
    assert is_due({**failed, "last_attempt_at": "2026-01-10 07:30:00"}, jan10)


def test_validation(ds):
    con, ws, dsid = ds
    with pytest.raises(ReportError):
        create_report(con, ws, dsid, name="x", recipients="not-an-email")
    with pytest.raises(ReportError):
        create_report(con, ws, dsid, name="x", recipients=[])
    with pytest.raises(ReportError):
        create_report(con, ws, dsid, name="x", recipients="a@b.co", frequency="hourly")
    with pytest.raises(ReportError):
        create_report(con, ws, dsid, name="x", recipients="a@b.co", measure="region")
    r = create_report(con, ws, dsid, name="Weekly", recipients="A@b.co, c@d.org; a@b.co")
    assert r["recipients"] == ["a@b.co", "c@d.org"]          # cleaned and de-duplicated


# ---------------------------------------------------------- delivery ---

def test_send_delivers_one_message_per_recipient(ds, smtp):
    con, ws, dsid = ds
    r = create_report(con, ws, dsid, name="Revenue weekly", recipients=["ceo@x.com", "cfo@x.com"],
                      measure="revenue")
    out = send_report(con, ws, r["report_id"])
    assert out["sent"] == 2
    assert [m[0] for m in smtp.messages] == [["ceo@x.com"], ["cfo@x.com"]]
    msg = smtp.messages[0][1]
    assert msg["To"] == "ceo@x.com" and "Revenue weekly" in msg["Subject"]
    assert "https://app.example.com/?ds=" in _body(msg, "plain")
    assert "Open the dashboard" in _body(msg, "html")
    for raw in RAW:
        assert raw not in _body(msg, "html")
    assert list_reports(con, ws)[0]["last_status"] == "sent"


def test_without_smtp_it_fails_loudly_and_records_why(ds, monkeypatch):
    con, ws, dsid = ds
    monkeypatch.setattr(config, "SMTP_HOST", "")
    r = create_report(con, ws, dsid, name="r", recipients="a@b.co")
    with pytest.raises(ReportError, match="not configured"):
        send_report(con, ws, r["report_id"])
    row = list_reports(con, ws)[0]
    assert row["last_status"] == "error" and "IH_SMTP_HOST" in row["last_error"]


def test_scheduler_sends_once_per_period(ds, smtp):
    con, ws, dsid = ds
    create_report(con, ws, dsid, name="daily", recipients="a@b.co", frequency="daily")
    create_report(con, ws, dsid, name="monthly", recipients="m@b.co", frequency="monthly")
    day1 = datetime(2026, 3, 1, 8)
    assert len(run_due_reports(con, day1)) == 2
    assert run_due_reports(con, day1.replace(hour=20)) == []          # same day: nothing
    assert len(run_due_reports(con, datetime(2026, 3, 2, 8))) == 1     # next day: daily only
    assert len(smtp.messages) == 3


# -------------------------------------------------------------- HTTP ---

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "reports_test.duckdb")
    from app.main import app

    return TestClient(app)


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_http_roles_preview_and_erasure(client, smtp):
    admin = client.post("/api/auth/signup", json={"email": "boss@example.com", "password": "supersecret1",
                                                  "workspace_name": "Acme"}).json()["access_token"]
    ds = client.post("/api/datasets/upload", files={"file": ("s.csv", _csv(SALES), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    client.post("/api/members", json={"email": "viewer@example.com", "role": "viewer",
                                      "password": "supersecret1"}, headers=auth(admin))
    vid = next(m["user_id"] for m in client.get("/api/members", headers=auth(admin)).json()
               if m["email"] == "viewer@example.com")
    viewer = client.post("/api/auth/login", json={"email": "viewer@example.com",
                                                  "password": "supersecret1"}).json()["access_token"]

    assert client.get("/api/reports/status", headers=auth(viewer)).json() == {"email_configured": True}
    body = {"name": "Board pack", "recipients": ["viewer@example.com", "x@y.org"], "measure": "revenue"}
    assert client.post(f"/api/datasets/{ds}/reports", json=body, headers=auth(viewer)).status_code == 403
    r = client.post(f"/api/datasets/{ds}/reports", json=body, headers=auth(admin))
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]

    prev = client.get(f"/api/datasets/{ds}/reports/preview", params={"measure": "revenue"},
                      headers=auth(admin)).json()
    assert "Revenue" in prev["subject"] and "priya.sharma@acme.com" not in prev["html"]

    assert client.post(f"/api/reports/{rid}/send", headers=auth(viewer)).status_code == 403
    assert client.post(f"/api/reports/{rid}/send", headers=auth(admin)).json()["sent"] == 2
    assert client.patch(f"/api/reports/{rid}", json={"enabled": False},
                        headers=auth(admin)).json()["enabled"] is False

    # erasing a member takes their address off every report
    client.delete(f"/api/privacy/member/{vid}", headers=auth(admin))
    reports = client.get(f"/api/datasets/{ds}/reports", headers=auth(admin)).json()
    assert reports[0]["recipients"] == ["x@y.org"]
    assert client.delete(f"/api/reports/{rid}", headers=auth(admin)).status_code == 200
    assert client.delete(f"/api/reports/{rid}", headers=auth(admin)).status_code == 404


def test_migration_creates_the_reports_table():
    import duckdb

    from app.core import db
    from app.core.migrations import run_migrations

    con = duckdb.connect(":memory:")
    con.execute(db.SCHEMA)
    con.execute("DROP TABLE report_schedules")
    run_migrations(con)
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'report_schedules'").fetchall()}
    assert {"report_id", "recipients", "frequency", "last_attempt_at"} <= cols
