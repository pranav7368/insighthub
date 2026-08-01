"""Structured logging, request correlation, and — the part that matters —
that logs never carry secrets or personal data.

A log shipped to a third-party service is a data transfer. A log containing
customer PII turns every log sink into a subprocessor, and a log containing a
bearer token hands out a session. Both are easy to cause by accident, so they
are tested rather than trusted.
"""

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core import observability


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "obs.duckdb")
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def caplogger():
    """Capture the app's own JSON log stream.

    The handler binds sys.stdout when the module is imported, which is before
    pytest replaces it — so capsys sees nothing and an assertion like
    "token not in output" would pass against an empty string. Attaching a
    handler is the only way to assert on these lines honestly.
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(observability.JsonFormatter())
    logger = observability.log
    logger.addHandler(handler)
    yield buffer
    logger.removeHandler(handler)


# ------------------------------------------------------------ redaction ---

def test_redacts_credential_shaped_keys():
    cleaned = observability.redact({
        "authorization": "Bearer abc.def.ghi",
        "password": "hunter2",
        "api_key": "sk-live-123",
        "Session-Cookie": "x",
        "workspace_id": "ws_123",
    })
    assert cleaned["authorization"] == "[redacted]"
    assert cleaned["password"] == "[redacted]"
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["Session-Cookie"] == "[redacted]"
    assert cleaned["workspace_id"] == "ws_123"      # identifiers are the point


def test_redacts_a_bearer_token_inside_free_text():
    cleaned = observability.redact("called with Bearer eyJhbGciOi.JIUzI1.NiIs and failed")
    assert "eyJhbGciOi" not in cleaned
    assert "[redacted]" in cleaned


def test_redaction_reaches_into_nested_structures():
    cleaned = observability.redact({"outer": {"list": [{"token": "abc"}]}})
    assert cleaned["outer"]["list"][0]["token"] == "[redacted]"


# --------------------------------------------------------- log format ----

def test_emits_one_json_object_per_line(caplog):
    formatter = observability.JsonFormatter()
    record = logging.LogRecord("insighthub", logging.INFO, __file__, 1, "request", None, None)
    record.context = {"status": 200, "path": "/api/datasets"}
    line = formatter.format(record)
    payload = json.loads(line)              # must parse — it is machine-read
    assert payload["message"] == "request"
    assert payload["status"] == 200
    assert "request_id" in payload


def test_context_is_redacted_in_the_formatted_line():
    formatter = observability.JsonFormatter()
    record = logging.LogRecord("insighthub", logging.ERROR, __file__, 1, "boom", None, None)
    record.context = {"password": "hunter2"}
    assert "hunter2" not in formatter.format(record)


# ------------------------------------------------------ request tracing ---

def test_every_response_carries_a_request_id(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Request-Id")


def test_a_supplied_request_id_is_preserved(client):
    """So a trace survives a proxy hop."""
    r = client.get("/api/health", headers={"X-Request-Id": "trace-me-123"})
    assert r.headers["X-Request-Id"] == "trace-me-123"


def test_request_ids_differ_between_requests(client):
    a = client.get("/api/health").headers["X-Request-Id"]
    b = client.get("/api/health").headers["X-Request-Id"]
    assert a != b


def test_the_request_log_never_contains_the_authorization_header(client, caplogger):
    """The header is on every authenticated request; logging it would hand out
    live sessions to whoever can read the logs."""
    token = client.post("/api/auth/signup", json={
        "email": "log@example.com", "password": "correct-horse-battery",
        "workspace_name": "Acme",
    }).json()["access_token"]
    caplogger.truncate(0)
    caplogger.seek(0)

    client.get("/api/datasets", headers={"Authorization": f"Bearer {token}"})
    output = caplogger.getvalue()
    assert output.strip(), "expected the request to be logged at all"
    assert token not in output
    assert "Bearer" not in output


def test_the_request_log_records_identifiers_not_contents(client, caplogger):
    client.post("/api/auth/signup", json={
        "email": "shape@example.com", "password": "correct-horse-battery",
        "workspace_name": "Acme",
    })
    caplogger.truncate(0)
    caplogger.seek(0)

    client.get("/api/datasets", headers={"Authorization": "Bearer nonsense"})
    lines = [ln for ln in caplogger.getvalue().splitlines() if ln.startswith("{")]
    assert lines, "expected a structured request line"
    payload = json.loads(lines[-1])
    assert payload["path"] == "/api/datasets"
    assert payload["method"] == "GET"
    assert isinstance(payload["duration_ms"], (int, float))
    # the email that was posted must never appear in a request log
    assert "shape@example.com" not in caplogger.getvalue()


def test_error_reporting_stays_local_without_a_dsn(monkeypatch, caplogger):
    """Default deployments send no outbound telemetry."""
    from app.core import config

    monkeypatch.setattr(config, "ERROR_DSN", "", raising=False)
    observability.report_exception(ValueError("kaboom"), where="test")
    assert "kaboom" in caplogger.getvalue()
