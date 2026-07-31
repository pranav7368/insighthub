"""DuckDB connection + multi-tenant metadata schema.

Multi-tenancy model: every row of business metadata carries a workspace_id
(the tenant). A per-file raw data table is created per dataset, and its
physical table name is namespaced with the workspace_id so two tenants can
upload files with identical names without collision. Every query in the
analytics/QA engines is scoped by workspace_id, and the API layer resolves
workspace_id from the authenticated principal - never from client-supplied
data (see api deps) - so one tenant can never read another's rows.
"""

import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

import duckdb

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id VARCHAR PRIMARY KEY,
    name         VARCHAR NOT NULL,
    created_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS users (
    user_id       VARCHAR PRIMARY KEY,
    workspace_id  VARCHAR NOT NULL,
    email         VARCHAR NOT NULL UNIQUE,
    password_hash VARCHAR NOT NULL,
    role          VARCHAR NOT NULL DEFAULT 'admin',   -- admin | viewer
    created_at    TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id    VARCHAR PRIMARY KEY,
    workspace_id  VARCHAR NOT NULL,
    name          VARCHAR NOT NULL,
    source_file   VARCHAR NOT NULL,
    kind          VARCHAR NOT NULL,      -- structured | document
    table_name    VARCHAR,               -- structured only: physical raw table
    row_count     INTEGER DEFAULT 0,
    char_count    INTEGER DEFAULT 0,
    ingested_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS dataset_columns (
    dataset_id     VARCHAR NOT NULL,
    workspace_id   VARCHAR NOT NULL,
    column_name    VARCHAR NOT NULL,
    role           VARCHAR NOT NULL,      -- measure | dimension | date | ignored
    subtype        VARCHAR,
    distinct_count INTEGER,
    overridden     BOOLEAN DEFAULT false,
    PRIMARY KEY (dataset_id, column_name)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     VARCHAR PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    dataset_id   VARCHAR NOT NULL,
    position     INTEGER NOT NULL,
    locator      VARCHAR,
    text         VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id     VARCHAR PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    embedding    DOUBLE[]
);

CREATE TABLE IF NOT EXISTS audit_log (
    ts           TIMESTAMP DEFAULT current_timestamp,
    workspace_id VARCHAR,
    user_id      VARCHAR,
    action       VARCHAR NOT NULL,
    detail       VARCHAR
);

-- Incremental ingestion (monthly appends): every append is a batch so it can
-- be listed and rolled back. Rows carry their batch id (internal _ih_batch
-- column on the raw table). Rows removed by a "replace period" append are
-- archived here as JSON so a rollback can restore them.
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id     VARCHAR PRIMARY KEY,
    dataset_id   VARCHAR NOT NULL,
    workspace_id VARCHAR NOT NULL,
    source_file  VARCHAR,
    mode         VARCHAR NOT NULL,       -- initial | append | replace_period | restore
    rows_added   INTEGER DEFAULT 0,
    rows_removed INTEGER DEFAULT 0,
    skipped_dupes INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS row_archive (
    batch_id     VARCHAR NOT NULL,
    workspace_id VARCHAR NOT NULL,
    dataset_id   VARCHAR NOT NULL,
    row_json     VARCHAR NOT NULL        -- one removed row (user columns) as JSON
);

-- Live data sources (connectors): a URL / Google Sheet that populates a
-- dataset and can be re-synced (manually or on a schedule). One source owns
-- one dataset; a sync is a full snapshot refresh of that dataset. The fetch
-- URL is validated against an SSRF guard before every request (see
-- ingest/connectors.py). Workspace-scoped like everything else.
CREATE TABLE IF NOT EXISTS data_sources (
    source_id                VARCHAR PRIMARY KEY,
    workspace_id             VARCHAR NOT NULL,
    dataset_id               VARCHAR,               -- populated after first successful sync
    name                     VARCHAR NOT NULL,
    kind                     VARCHAR NOT NULL,      -- url_csv | google_sheet
    url                      VARCHAR NOT NULL,
    refresh_interval_minutes INTEGER DEFAULT 0,     -- 0 = manual refresh only
    status                   VARCHAR DEFAULT 'pending',  -- pending | ok | error
    last_error               VARCHAR,
    last_synced              TIMESTAMP,
    row_count                INTEGER DEFAULT 0,
    created_at               TIMESTAMP DEFAULT current_timestamp
);

-- Saved dashboard views: a named, persisted dashboard configuration for a
-- dataset (active filters, date range, chosen measure, and which sections are
-- hidden). One view per dataset can be the default (auto-applied on open).
-- The config is a validated JSON blob (see analytics/views.py). Workspace +
-- dataset scoped like everything else.
CREATE TABLE IF NOT EXISTS dashboard_views (
    view_id      VARCHAR PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    dataset_id   VARCHAR NOT NULL,
    name         VARCHAR NOT NULL,
    config       VARCHAR NOT NULL,      -- JSON: filters/date_from/date_to/measure/hidden_sections/section_order
    is_default   BOOLEAN DEFAULT false,
    created_at   TIMESTAMP DEFAULT current_timestamp,
    updated_at   TIMESTAMP DEFAULT current_timestamp
);

-- Public share links: a revocable, optionally-expiring, READ-ONLY capability
-- token granting unauthenticated access to exactly one dataset's dashboard
-- (optionally pinned to a saved view). The token is a 192-bit random string;
-- possession of it is the only credential (see analytics/sharing.py). This is
-- the single place a workspace boundary is crossed without a JWT, and only for
-- the one dataset the token names.
CREATE TABLE IF NOT EXISTS share_links (
    token        VARCHAR PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    dataset_id   VARCHAR NOT NULL,
    view_id      VARCHAR,               -- optional: pin to a saved view's config
    label        VARCHAR,
    created_by   VARCHAR,
    expires_at   TIMESTAMP,             -- NULL = never expires
    revoked      BOOLEAN DEFAULT false,
    created_at   TIMESTAMP DEFAULT current_timestamp
);

-- Threshold alerts: watch a measure on a dataset and POST to a webhook when a
-- condition is met. Evaluated by the background scheduler; the webhook fires
-- only on the transition into 'firing' (re-arms when it returns to 'ok') so a
-- persistent condition never spams. Values are computed deterministically from
-- the data (analytics/alerts.py) — grounded, like everything else.
CREATE TABLE IF NOT EXISTS alerts (
    alert_id      VARCHAR PRIMARY KEY,
    workspace_id  VARCHAR NOT NULL,
    dataset_id    VARCHAR NOT NULL,
    name          VARCHAR NOT NULL,
    measure       VARCHAR NOT NULL,
    aggregate     VARCHAR NOT NULL,     -- total | latest | mom_pct
    op            VARCHAR NOT NULL,     -- lt | lte | gt | gte
    threshold     DOUBLE  NOT NULL,
    webhook_url   VARCHAR NOT NULL,
    enabled       BOOLEAN DEFAULT true,
    last_checked  TIMESTAMP,
    last_value    DOUBLE,
    last_state    VARCHAR DEFAULT 'pending',  -- pending | ok | firing | error
    last_error    VARCHAR,
    last_fired_at TIMESTAMP,
    created_at    TIMESTAMP DEFAULT current_timestamp
);

-- Certified metrics (a small semantic layer): a blessed, reusable metric
-- definition for a dataset — an aggregate (SUM(revenue)) or a ratio
-- (SUM(profit)/SUM(revenue)). Definitions are CONSTRAINED (aggregate chosen
-- from a whitelist, every column validated against the dataset's real
-- columns) — never free-form SQL. See analytics/semantic.py.
CREATE TABLE IF NOT EXISTS metrics (
    metric_id    VARCHAR PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    dataset_id   VARCHAR NOT NULL,
    name         VARCHAR NOT NULL,
    kind         VARCHAR NOT NULL,      -- aggregate | ratio
    definition   VARCHAR NOT NULL,      -- JSON (constrained spec)
    format       VARCHAR,               -- number | currency | percent
    created_at   TIMESTAMP DEFAULT current_timestamp
);

-- Billing: one subscription row per workspace (absent = free/active). Plan
-- gating is opt-in (IH_BILLING_ENABLED); Stripe fields are populated by the
-- billing webhook, or a plan can be set manually (self-hosted). See
-- app/billing.py.
CREATE TABLE IF NOT EXISTS subscriptions (
    workspace_id           VARCHAR PRIMARY KEY,
    plan                   VARCHAR NOT NULL DEFAULT 'free',    -- free | pro
    status                 VARCHAR NOT NULL DEFAULT 'active',  -- active | trialing | past_due | canceled
    stripe_customer_id     VARCHAR,
    stripe_subscription_id VARCHAR,
    current_period_end     TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT current_timestamp
);

-- Multi-table joins: a relation links two structured datasets on a key and the
-- join is materialized into a new structured dataset (`dataset_id`), so every
-- existing analytic (dashboard/metrics/drivers/ask) works on it unchanged. The
-- relation is kept so the joined dataset can be rebuilt from fresh source data.
CREATE TABLE IF NOT EXISTS dataset_relations (
    relation_id       VARCHAR PRIMARY KEY,
    workspace_id      VARCHAR NOT NULL,
    dataset_id        VARCHAR NOT NULL,   -- the materialized joined dataset
    left_dataset_id   VARCHAR NOT NULL,
    right_dataset_id  VARCHAR NOT NULL,
    left_key          VARCHAR NOT NULL,
    right_key         VARCHAR NOT NULL,
    join_type         VARCHAR NOT NULL,   -- inner | left
    created_at        TIMESTAMP DEFAULT current_timestamp
);
"""

# Internal provenance column added to every structured raw table. Kept out of
# `dataset_columns`, so it is invisible to detection, dashboards and Q&A.
BATCH_COL = "_ih_batch"


# Whether the metadata schema has been created for the current Postgres target
# in this process (idempotent CREATE IF NOT EXISTS still, but skip the churn).
_pg_schema_ready = False


def _pg_conn_string(url: str) -> str:
    """Convert a postgresql:// URL into a libpq keyword string for DuckDB ATTACH."""
    u = urlparse(url)
    parts = []
    if u.hostname:
        parts.append(f"host={u.hostname}")
    if u.port:
        parts.append(f"port={u.port}")
    dbname = (u.path or "").lstrip("/")
    if dbname:
        parts.append(f"dbname={dbname}")
    if u.username:
        parts.append(f"user={unquote(u.username)}")
    if u.password:
        parts.append(f"password={unquote(u.password)}")
    return " ".join(parts)


def _connect_postgres() -> duckdb.DuckDBPyConnection:
    """A DuckDB connection whose default catalog is a Postgres database (ATTACH).
    The app's existing DuckDB SQL runs unchanged; storage lives in Postgres."""
    global _pg_schema_ready
    con = duckdb.connect()
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    attach_arg = _pg_conn_string(config.DATABASE_URL).replace("'", "''")  # escape for the SQL string literal
    con.execute(f"ATTACH '{attach_arg}' AS pg (TYPE POSTGRES)")
    con.execute("USE pg")
    if not _pg_schema_ready:
        con.execute(SCHEMA)
        _pg_schema_ready = True
    return con


# Per-thread connection cache. A worker thread serves one request at a time, so
# reusing its connection across requests is safe (never used concurrently) and
# avoids re-opening / re-ATTACHing every request.
_tls = threading.local()


def _new_connection() -> duckdb.DuckDBPyConnection:
    if config.DATABASE_URL:
        return _connect_postgres()
    path = config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def _target_key() -> str:
    return f"pg:{config.DATABASE_URL}" if config.DATABASE_URL else f"duck:{config.DB_PATH}"


def connect(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    # An explicit path always gets a fresh, unpooled connection (tools/tests).
    if db_path is not None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path))
        con.execute(SCHEMA)
        return con

    if not config.DB_POOL_ENABLED:
        return _new_connection()

    cache = getattr(_tls, "cache", None)
    if cache is None:
        cache = {}
        _tls.cache = cache
    key = _target_key()
    con = cache.get(key)
    if con is None:
        con = _new_connection()
        cache[key] = con
    return con


def audit(con, workspace_id: str | None, user_id: str | None, action: str, detail: str = "") -> None:
    con.execute(
        "INSERT INTO audit_log (workspace_id, user_id, action, detail) VALUES (?, ?, ?, ?)",
        [workspace_id, user_id, action, detail],
    )
