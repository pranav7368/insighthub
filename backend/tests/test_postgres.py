"""Postgres backend: the real ingest + analytics run through DuckDB->Postgres
ATTACH. Skipped automatically when no Postgres is reachable (e.g. CI)."""

import os
import uuid

import pytest

from app.core import config, db

PG_URL = os.environ.get("IH_TEST_DATABASE_URL",
                        "postgresql://insighthub:insighthub@localhost:5544/insighthub")


@pytest.fixture()
def pg(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", PG_URL)
    monkeypatch.setattr(db, "_pg_schema_ready", False)
    try:
        con = db.connect()
        con.execute("SELECT 1")
    except Exception as exc:  # no Postgres here → skip, don't fail
        pytest.skip(f"Postgres not reachable: {exc}")
    return con


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
