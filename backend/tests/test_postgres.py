"""Postgres backend: the real ingest + analytics run through DuckDB->Postgres
ATTACH. Skipped automatically when no Postgres is reachable (e.g. CI)."""

import os
import uuid

import pytest

from app.core import config, db

PG_URL = os.environ.get("IH_TEST_DATABASE_URL",
                        "postgresql://insighthub:insighthub@localhost:5544/insighthub")


def _postgres_reachable() -> str | None:
    """Raw connectivity probe — no schema, no migrations.

    Deliberately separate from the fixture below. The fixture used to wrap
    db.connect() in `except Exception: skip`, which meant a MIGRATION failure
    was reported as "Postgres not reachable" and silently skipped. That is
    exactly how a broken Postgres deployment passed CI while every one of 497
    tests was green: the only tests that touch Postgres skipped themselves.
    Connectivity decides the skip; everything after it is allowed to fail.
    """
    import duckdb

    try:
        probe = duckdb.connect()
        probe.execute("INSTALL postgres")
        probe.execute("LOAD postgres")
        probe.execute(f"ATTACH '{db._pg_conn_string(PG_URL)}' AS probe_pg (TYPE POSTGRES)")
        probe.close()
        return None
    except Exception as exc:                      # noqa: BLE001
        return str(exc)


@pytest.fixture()
def pg(monkeypatch):
    unreachable = _postgres_reachable()
    if unreachable:
        pytest.skip(f"Postgres not reachable: {unreachable}")

    monkeypatch.setattr(config, "DATABASE_URL", PG_URL)
    monkeypatch.setattr(db, "_pg_schema_ready", False)
    # No try/except: schema or migration errors must FAIL, not skip.
    con = db.connect()
    con.execute("SELECT 1")
    return con


def test_every_migration_applies_on_postgres(pg):
    """The regression this file exists for.

    `BOOLEAN DEFAULT false` in an ALTER TABLE is accepted by DuckDB's own
    engine and rejected through its Postgres extension ("only constant DEFAULT
    expressions are supported"). The file backend was therefore perfectly
    healthy while the Postgres deployment could not start at all.
    """
    from app.core.migrations import MIGRATIONS, pending_ids

    assert pending_ids(pg) == [], "every migration must apply cleanly on Postgres"

    # and the columns those migrations add are really there
    for table, column in [("users", "mfa_enabled"), ("users", "token_epoch"),
                          ("workspaces", "require_mfa"), ("alerts", "created_by"),
                          ("share_links", "created_by")]:
        pg.execute(f"SELECT {column} FROM {table} LIMIT 1")     # raises if missing
    assert len(MIGRATIONS) >= 8


def test_readiness_probe_succeeds_on_postgres(pg):
    """What /api/ready checks. It returned 503 for a fully-built stack because
    db.connect() raised inside the migration step."""
    assert pg.execute("SELECT 1").fetchone()[0] == 1


def test_schema_and_params_on_postgres(pg):
    ws = "ws_" + uuid.uuid4().hex[:10]
    pg.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)", [ws, "PG test"])
    got = pg.execute("SELECT name FROM workspaces WHERE workspace_id = ?", [ws]).fetchone()
    assert got[0] == "PG test"


def test_full_pipeline_and_dashboard_on_postgres(pg):
    from app.analytics.engine import compute_dashboard
    from app.analytics.drivers import explain_change
    from app.ingest.pipeline import ingest_upload

    ws = "ws_" + uuid.uuid4().hex[:10]
    pg.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)", [ws, "PG"])
    csv_bytes = (b"date,branch,revenue\n"
                 b"2025-01-05,Delhi,1000\n2025-01-06,Mumbai,2000\n"
                 b"2025-02-05,Delhi,1500\n2025-02-06,Mumbai,1200\n")

    # register(df) + CREATE TABLE AS + auto-detection, all against Postgres
    res = ingest_upload(pg, ws, "sales.csv", csv_bytes)
    dash = compute_dashboard(pg, ws, res.dataset_id)   # strftime/date_trunc/TRY_CAST/aggregates on PG
    rev = next(k for k in dash["kpis"] if k["column"] == "revenue")
    assert rev["total"] == 5700

    # driver analysis (period comparison) on Postgres
    ex = explain_change(pg, ws, res.dataset_id)
    assert ex["available"] and ex["delta"] == -300   # Jan 3000 -> Feb 2700

    # cleanup this run's physical table so the test db doesn't accumulate
    tbl = pg.execute("SELECT table_name FROM datasets WHERE dataset_id = ?", [res.dataset_id]).fetchone()[0]
    pg.execute(f'DROP TABLE IF EXISTS "{tbl}"')
    pg.execute("DELETE FROM datasets WHERE workspace_id = ?", [ws])
    pg.execute("DELETE FROM dataset_columns WHERE workspace_id = ?", [ws])
