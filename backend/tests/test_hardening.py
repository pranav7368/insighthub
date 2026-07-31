"""Production hardening: rate limiter, CORS/secret guardrails, headers."""

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.ratelimit import RateLimiter, bucket_for


# ---------------------------------------------------- rate limiter unit ----

def test_rate_limiter_blocks_after_limit():
    clock = {"t": 1000.0}
    rl = RateLimiter(clock=lambda: clock["t"])
    for _ in range(3):
        assert rl.check("k", limit=3, window=60)[0] is True
    ok, retry = rl.check("k", limit=3, window=60)
    assert ok is False and retry > 0


def test_rate_limiter_window_slides():
    clock = {"t": 0.0}
    rl = RateLimiter(clock=lambda: clock["t"])
    assert rl.check("k", 1, 60)[0] is True
    assert rl.check("k", 1, 60)[0] is False   # within window
    clock["t"] = 61.0                          # window passed
    assert rl.check("k", 1, 60)[0] is True


def test_rate_limiter_keys_are_independent():
    rl = RateLimiter()
    assert rl.check("a", 1, 60)[0] is True
    assert rl.check("b", 1, 60)[0] is True     # different key, own budget


def test_bucket_routing():
    assert bucket_for("/api/auth/login", config)[0] == "auth"
    assert bucket_for("/api/ask", config)[0] == "llm"
    assert bucket_for("/api/datasets/x/query", config)[0] == "llm"
    assert bucket_for("/api/datasets/x/narrative", config)[0] == "llm"
    assert bucket_for("/api/public/tok/dashboard", config)[0] == "public"
    assert bucket_for("/api/datasets", config)[0] == "default"


# --------------------------------------------------- production guard ------

def test_production_requires_secret_and_cors(monkeypatch):
    from app.main import _production_issues
    monkeypatch.setattr(config, "ENV", "production")
    monkeypatch.setattr(config, "SECRET_KEY", "dev-only-insecure-change-me-0000000000000000")
    monkeypatch.setattr(config, "CORS_ORIGINS", "")
    issues = _production_issues()
    assert any("SECRET_KEY" in i for i in issues) and any("CORS" in i for i in issues)

    monkeypatch.setattr(config, "SECRET_KEY", "a-real-long-random-secret-value-1234567890")
    monkeypatch.setattr(config, "CORS_ORIGINS", "https://app.example.com")
    assert _production_issues() == []


def test_development_has_no_issues(monkeypatch):
    from app.main import _production_issues
    monkeypatch.setattr(config, "ENV", "development")
    assert _production_issues() == []


# --------------------------------------------------- middleware live -------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "harden.duckdb")
    from app.main import app
    from app.core import ratelimit
    ratelimit.limiter.reset()
    return TestClient(app)


def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_rate_limit_returns_429(client, monkeypatch):
    from app.core import ratelimit
    ratelimit.limiter.reset()
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(config, "RATELIMIT_AUTH", 3)
    # 3 allowed, the 4th login attempt is throttled (brute-force guard)
    codes = [client.post("/api/auth/login", json={"email": "x@x.com", "password": "nope12345"}).status_code
             for _ in range(4)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429


def test_health_is_not_rate_limited(client, monkeypatch):
    from app.core import ratelimit
    ratelimit.limiter.reset()
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(config, "RATELIMIT_DEFAULT", 1)
    assert all(client.get("/api/health").status_code == 200 for _ in range(5))


def test_readiness_probe(client):
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["backend"] in ("duckdb", "postgres")


# ------------------------------------------------- connection pooling ------

def test_pool_reuses_connection_per_thread(tmp_path, monkeypatch):
    from app.core import db
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pool.duckdb")
    monkeypatch.setattr(config, "DB_POOL_ENABLED", True)
    db._tls.__dict__.pop("cache", None)  # fresh thread-local cache for this test
    a = db.connect()
    b = db.connect()
    assert a is b  # same target + same thread → reused, not reopened


def test_pool_disabled_returns_fresh(tmp_path, monkeypatch):
    from app.core import db
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "nopool.duckdb")
    monkeypatch.setattr(config, "DB_POOL_ENABLED", False)
    assert db.connect() is not db.connect()  # no pooling → distinct connections


def test_explicit_path_bypasses_pool(tmp_path, monkeypatch):
    from app.core import db
    monkeypatch.setattr(config, "DB_POOL_ENABLED", True)
    p = str(tmp_path / "explicit.duckdb")
    assert db.connect(p) is not db.connect(p)  # explicit path is never pooled
