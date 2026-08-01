"""Central configuration. Secrets come from the environment, never code."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("IH_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("IH_DB", DATA_DIR / "insighthub.duckdb"))

# Storage backend. Unset (default) = single-file DuckDB (zero-config dev). Set a
# Postgres URL (postgresql://user:pass@host:port/dbname) to store everything in
# Postgres instead — DuckDB stays the query engine and ATTACHes to it, so the
# same SQL runs, but data is durable and supports concurrent connections.
DATABASE_URL = os.environ.get("IH_DATABASE_URL", "").strip()

# Connection pooling: reuse one DB connection per worker thread instead of
# opening (and, for Postgres, re-ATTACHing) on every request. On by default in
# real runs; disabled under tests so each test's monkeypatched target is honored.
DB_POOL_ENABLED = os.environ.get("IH_DB_POOL", "1").lower() in ("1", "true", "yes")

# Observability. LOG_LEVEL controls verbosity; ERROR_DSN is an OPT-IN hook for
# an error-tracking service — unset means nothing leaves the machine.
LOG_LEVEL = os.environ.get("IH_LOG_LEVEL", "info")
ERROR_DSN = os.environ.get("IH_ERROR_DSN", "")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

OFFLINE = os.environ.get("IH_OFFLINE", "").lower() in ("1", "true", "yes")

# --- LLM provider (any provider, not just Claude) --------------------------
# IH_LLM_PROVIDER: anthropic | openai | gemini | ollama | groq | openrouter |
#                  together | offline. Empty = auto (anthropic if its key is
#                  present, else offline).
LLM_PROVIDER = os.environ.get("IH_LLM_PROVIDER", "").lower().strip()
# IH_MODEL overrides the per-provider default model.
MODEL = os.environ.get("IH_MODEL", "").strip()
# Optional overrides for any OpenAI-compatible endpoint.
LLM_BASE_URL = os.environ.get("IH_LLM_BASE_URL", "").strip()
LLM_API_KEY = os.environ.get("IH_LLM_API_KEY", "").strip()

# Deployment environment. In "production" the app refuses to start with the
# insecure default secret or wide-open CORS (see main._production_issues).
ENV = os.environ.get("IH_ENV", "development").lower().strip()

# Auth. IH_SECRET_KEY MUST be set in any real deployment - the default is a
# development-only value and the app warns loudly if it is used with auth on.
SECRET_KEY = os.environ.get("IH_SECRET_KEY", "dev-only-insecure-change-me-0000000000000000")
JWT_ALG = "HS256"
JWT_TTL_MINUTES = int(os.environ.get("IH_JWT_TTL_MINUTES", "720"))

# CORS: a comma-separated allow-list of exact origins (e.g.
# "https://app.example.com"). Empty falls back to a permissive localhost regex
# for local development only.
CORS_ORIGINS = os.environ.get("IH_CORS_ORIGINS", "").strip()

# Rate limiting (per client IP, 60s window). Disabled automatically under tests.
RATE_LIMIT_ENABLED = os.environ.get("IH_RATELIMIT_ENABLED", "1").lower() in ("1", "true", "yes")
RATELIMIT_AUTH = int(os.environ.get("IH_RATELIMIT_AUTH", "15"))       # login/signup — brute-force guard
RATELIMIT_LLM = int(os.environ.get("IH_RATELIMIT_LLM", "40"))        # ask/query/narrative — expensive
RATELIMIT_PUBLIC = int(os.environ.get("IH_RATELIMIT_PUBLIC", "120"))  # public share links
RATELIMIT_DEFAULT = int(os.environ.get("IH_RATELIMIT_DEFAULT", "400"))
RATELIMIT_WINDOW = int(os.environ.get("IH_RATELIMIT_WINDOW", "60"))
# Trust X-Forwarded-For for the client IP (only enable behind a proxy you control).
TRUST_PROXY = os.environ.get("IH_TRUST_PROXY", "").lower() in ("1", "true", "yes")

# --- Billing / plan gating (opt-in) ----------------------------------------
# Off by default: every workspace is unlimited (how self-hosted installs run).
# Turn on to enforce free-tier caps; a paid subscription lifts them.
BILLING_ENABLED = os.environ.get("IH_BILLING_ENABLED", "").lower() in ("1", "true", "yes")
STRIPE_SECRET_KEY = os.environ.get("IH_STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("IH_STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_PRICES = {"pro": os.environ.get("IH_STRIPE_PRICE_PRO", "").strip()}

# Upload safety limits.
MAX_UPLOAD_BYTES = int(os.environ.get("IH_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))  # 50 MB
ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xlsm", ".pdf", ".docx", ".txt", ".md"}

# --- Live data sources (URL / Google Sheet connectors) ---------------------
# Time budget for fetching a remote source, and the redirect cap.
SOURCE_FETCH_TIMEOUT = int(os.environ.get("IH_SOURCE_TIMEOUT", "20"))
SOURCE_MAX_REDIRECTS = int(os.environ.get("IH_SOURCE_MAX_REDIRECTS", "5"))
# SSRF guard: by default the fetcher refuses any URL that resolves to a
# private / loopback / link-local / reserved address (blocks cloud-metadata
# and internal-network probing). Set this only if you intentionally sync from
# an internal URL on your own trusted network.
ALLOW_PRIVATE_FETCH = os.environ.get("IH_ALLOW_PRIVATE_FETCH", "").lower() in ("1", "true", "yes")
# Background auto-refresh: periodically re-sync sources that have a refresh
# interval. On by default; disable for single-shot/CLI use or multi-worker
# deploys where a dedicated scheduler owns refreshes instead.
ENABLE_SCHEDULER = os.environ.get("IH_ENABLE_SCHEDULER", "1").lower() in ("1", "true", "yes")
SCHEDULER_TICK_SECONDS = int(os.environ.get("IH_SCHEDULER_TICK", "60"))

# Column-role detection thresholds (see analytics/detect.py).
MAX_DIMENSION_CARDINALITY = 40
MAX_NUMERIC_DIMENSION_CARDINALITY = 12

# Chunking (Q&A side).
CHUNK_CHARS = int(os.environ.get("IH_CHUNK_CHARS", "1200"))
CHUNK_OVERLAP = int(os.environ.get("IH_CHUNK_OVERLAP", "200"))
MIN_CHUNK_CHARS = 20
TOP_K = int(os.environ.get("IH_TOP_K", "8"))
CAG_MAX_CORPUS_CHARS = int(os.environ.get("IH_CAG_MAX_CHARS", "300000"))

RANDOM_SEED = 42


def prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
