"""Schema migrations.

The test that matters is the last one: a database created *before* a column
existed must gain it, because that is precisely the case `CREATE TABLE IF NOT
EXISTS` cannot handle and the reason this module exists.
"""

import duckdb
import pytest

from app.core import db
from app.core.migrations import MIGRATIONS, applied_ids, pending_ids, run_migrations


@pytest.fixture()
def fresh():
    con = duckdb.connect(":memory:")
    con.execute(db.SCHEMA)
    yield con
    con.close()


def test_ids_are_unique_and_sorted():
    ids = [m.id for m in MIGRATIONS]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids), "ids are applied in order — keep them sortable"


def test_every_migration_is_described():
    for m in MIGRATIONS:
        assert m.description.strip(), f"{m.id} needs a description"


def test_runs_once_and_records_what_it_did(fresh):
    applied = run_migrations(fresh)
    assert applied == [m.id for m in MIGRATIONS]
    assert applied_ids(fresh) == {m.id for m in MIGRATIONS}
    assert pending_ids(fresh) == []


def test_is_idempotent(fresh):
    run_migrations(fresh)
    assert run_migrations(fresh) == []          # nothing re-applied
    assert pending_ids(fresh) == []


def test_partial_state_converges(fresh):
    """A database that recorded only some ids applies exactly the rest."""
    run_migrations(fresh)
    fresh.execute("DELETE FROM schema_migrations WHERE id = ?", [MIGRATIONS[-1].id])
    assert run_migrations(fresh) == [MIGRATIONS[-1].id]


def test_an_older_database_gains_a_missing_column():
    """The actual bug this module exists for.

    Build a database the way an early release would have — without
    `alerts.created_by` — then migrate it and confirm the column arrives. With
    only CREATE TABLE IF NOT EXISTS this silently does nothing and the next
    release breaks on a customer's data.
    """
    con = duckdb.connect(":memory:")
    # an early release's alerts table — no created_by
    con.execute("""
        CREATE TABLE alerts (
            alert_id     VARCHAR PRIMARY KEY,
            workspace_id VARCHAR NOT NULL,
            dataset_id   VARCHAR NOT NULL,
            name         VARCHAR NOT NULL
        )
    """)
    con.execute("INSERT INTO alerts VALUES ('a1', 'ws', 'ds', 'legacy alert')")

    def columns():
        return {r[1] for r in con.execute("PRAGMA table_info('alerts')").fetchall()}

    # upgrading runs SCHEMA first, exactly as db.connect() does
    con.execute(db.SCHEMA)
    assert "created_by" not in columns(), (
        "CREATE TABLE IF NOT EXISTS skipped the existing table — this is the "
        "silent failure migrations exist to fix"
    )

    run_migrations(con)
    assert "created_by" in columns()
    # and the existing row survived
    assert con.execute("SELECT name FROM alerts WHERE alert_id = 'a1'").fetchone()[0] == "legacy alert"
    con.close()


def test_connect_migrates_automatically(tmp_path, monkeypatch):
    """Opening a connection is enough — no operator step to forget on deploy."""
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "auto.duckdb")
    monkeypatch.setattr(db.config, "DB_POOL_ENABLED", False)
    con = db.connect()
    assert pending_ids(con) == []
