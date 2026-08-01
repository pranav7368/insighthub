"""Backup and restore.

The load-bearing test here is `test_full_round_trip_through_the_api`: real data
goes in through HTTP, gets backed up, the database is wiped, the archive is
restored, and the dashboard is asked the same question again. Everyone has
backups; the people who lose data are the ones who never tried a restore.
"""

import csv
import io
import json
import pathlib

import duckdb
import pytest

from app.core import db
from app.core.backup import (
    BackupError, create_backup, prune, read_manifest, restore_backup, verify_backup,
)
from app.core.migrations import run_migrations

STRONG = "correct-horse-battery"
SALES = [["date", "region", "revenue"],
         ["2025-01-05", "North", "1000"],
         ["2025-02-06", "South", "2000"],
         ["2025-03-07", "East", "3000"]]


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fresh():
    con = duckdb.connect(":memory:")
    con.execute(db.SCHEMA)
    run_migrations(con)
    yield con
    con.close()


def _seed(con, workspace="ws_a"):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)", [workspace, "Acme"])
    con.execute("INSERT INTO users (user_id, workspace_id, email, password_hash, role) "
                "VALUES (?, ?, ?, 'hash', 'admin')",
                [f"usr_{workspace}", workspace, f"{workspace}@example.com"])
    con.execute("INSERT INTO datasets (dataset_id, workspace_id, name, source_file, kind, "
                "table_name, row_count) VALUES (?, ?, 'Sales', 's.csv', 'structured', ?, 3)",
                [f"ds_{workspace}", workspace, f"t_raw_{workspace}"])
    con.execute(f'CREATE TABLE "t_raw_{workspace}" (region VARCHAR, revenue INT)')
    con.execute(f"INSERT INTO \"t_raw_{workspace}\" VALUES ('North', 1000), ('South', 2000)")


# ------------------------------------------------------------- backup ----

def test_backup_writes_a_manifest_and_a_file_per_table(fresh, tmp_path):
    _seed(fresh)
    manifest = create_backup(fresh, tmp_path / "b1")

    assert manifest["format"] == 1
    assert manifest["tables"]["workspaces"] == 1
    assert manifest["tables"]["t_raw_ws_a"] == 2, "per-dataset raw tables must be included"
    for table in manifest["tables"]:
        assert (tmp_path / "b1" / f"{table}.parquet").exists()


def test_backup_records_the_schema_version(fresh, tmp_path):
    """So a newer archive is never half-restored into an older build."""
    manifest = create_backup(fresh, tmp_path / "b1")
    assert manifest["schema_migrations"], "the applied migrations must be recorded"


def test_backup_refuses_to_overwrite_an_existing_archive(fresh, tmp_path):
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")
    with pytest.raises(BackupError, match="not empty"):
        create_backup(fresh, tmp_path / "b1")


# ------------------------------------------------------------ restore ----

def test_round_trip_preserves_every_row(fresh, tmp_path):
    _seed(fresh)
    before = fresh.execute('SELECT * FROM "t_raw_ws_a" ORDER BY region').fetchall()
    create_backup(fresh, tmp_path / "b1")

    target = duckdb.connect(":memory:")
    result = restore_backup(target, tmp_path / "b1")

    assert result["restored"]["workspaces"] == 1
    after = target.execute('SELECT * FROM "t_raw_ws_a" ORDER BY region').fetchall()
    assert after == before, "restored rows must be identical, not merely as many"
    target.close()


def test_restore_recreates_the_per_dataset_tables(fresh, tmp_path):
    """These are created on upload, not by the schema, so a restore that only
    replays the schema would come back with dashboards pointing at nothing."""
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")

    target = duckdb.connect(":memory:")
    restore_backup(target, tmp_path / "b1")
    assert target.execute('SELECT count(*) FROM "t_raw_ws_a"').fetchone()[0] == 2
    target.close()


def test_restore_refuses_to_overwrite_populated_data(fresh, tmp_path):
    """Losing data *during a restore* is a particularly bitter way to lose it."""
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")

    other = duckdb.connect(":memory:")
    other.execute(db.SCHEMA)
    run_migrations(other)
    _seed(other, "ws_existing")

    with pytest.raises(BackupError, match="already contains data"):
        restore_backup(other, tmp_path / "b1")
    restore_backup(other, tmp_path / "b1", force=True)      # explicit is fine
    other.close()


def test_restore_refuses_an_archive_from_a_newer_build(fresh, tmp_path):
    """It would half-fit — tables present, columns missing — and corrupt
    quietly, which is worse than failing."""
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")

    manifest_path = tmp_path / "b1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_migrations"].append("9999_from_the_future")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    target = duckdb.connect(":memory:")
    with pytest.raises(BackupError, match="newer version"):
        restore_backup(target, tmp_path / "b1")
    target.close()


def test_restore_reports_an_incomplete_archive(fresh, tmp_path):
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")
    (tmp_path / "b1" / "workspaces.parquet").unlink()

    target = duckdb.connect(":memory:")
    with pytest.raises(BackupError, match="incomplete"):
        restore_backup(target, tmp_path / "b1")
    target.close()


def test_restoring_something_that_is_not_a_backup_fails_clearly(tmp_path):
    (tmp_path / "random").mkdir()
    target = duckdb.connect(":memory:")
    with pytest.raises(BackupError, match="does not look like a backup"):
        restore_backup(target, tmp_path / "random")
    target.close()


# -------------------------------------------------------------- verify ---

def test_verify_passes_a_good_archive(fresh, tmp_path):
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")
    assert verify_backup(tmp_path / "b1")["ok"] is True


def test_verify_catches_a_damaged_archive(fresh, tmp_path):
    """An unreadable archive should be found on a schedule, not on the worst
    day of the year."""
    _seed(fresh)
    create_backup(fresh, tmp_path / "b1")
    (tmp_path / "b1" / "workspaces.parquet").write_bytes(b"not parquet at all")

    with pytest.raises(BackupError, match="damaged"):
        verify_backup(tmp_path / "b1")


# --------------------------------------------------------------- prune ---

def test_prune_keeps_the_newest(fresh, tmp_path):
    for i in range(4):
        create_backup(fresh, tmp_path / f"b{i}")
        # nudge the timestamps apart so ordering is deterministic
        m = tmp_path / f"b{i}" / "manifest.json"
        data = json.loads(m.read_text(encoding="utf-8"))
        data["created_at"] = f"2026-01-0{i + 1}T00:00:00+00:00"
        m.write_text(json.dumps(data), encoding="utf-8")

    removed = prune(tmp_path, keep=2)
    assert sorted(removed) == ["b0", "b1"]
    assert (tmp_path / "b3").exists() and (tmp_path / "b2").exists()


def test_prune_refuses_to_delete_everything(tmp_path):
    with pytest.raises(BackupError, match="not a policy"):
        prune(tmp_path, keep=0)


# ---------------------------------------------------- the real round trip --

def test_full_round_trip_through_the_api(tmp_path, monkeypatch):
    """The test this module exists for.

    Real data in through HTTP, backed up, database destroyed, restored, and the
    same question asked again. Anything less is a claim, not a tested restore.
    """
    from fastapi.testclient import TestClient

    from app.core import config

    live = tmp_path / "live.duckdb"
    monkeypatch.setattr(config, "DB_PATH", live)
    monkeypatch.setattr(config, "DB_POOL_ENABLED", False)
    from app.main import app

    client = TestClient(app)
    token = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": STRONG, "workspace_name": "Acme",
    }).json()["access_token"]
    dataset_id = client.post(
        "/api/datasets/upload",
        files={"file": ("sales.csv", _csv(SALES), "text/csv")},
        headers=auth(token),
    ).json()["dataset_id"]

    original = client.get(f"/api/datasets/{dataset_id}/dashboard",
                          headers=auth(token)).json()["kpis"][0]["total"]
    assert original == 6000

    create_backup(db.connect(), tmp_path / "archive")

    # destroy everything, exactly as losing the disk would
    con = db.connect()
    for (table,) in con.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema NOT IN ('information_schema', 'pg_catalog')"""
    ).fetchall():
        con.execute(f'DROP TABLE IF EXISTS "{table}"')
    assert con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema', 'pg_catalog')"
    ).fetchone()[0] == 0

    restore_backup(db.connect(), tmp_path / "archive", force=True)

    # the same login and the same question must work again
    again = client.post("/api/auth/login",
                        json={"email": "boss@example.com", "password": STRONG})
    assert again.status_code == 200, "the restored database must still authenticate"
    restored_token = again.json()["access_token"]

    total = client.get(f"/api/datasets/{dataset_id}/dashboard",
                       headers=auth(restored_token)).json()["kpis"][0]["total"]
    assert total == original, "the dashboard must compute the same number after a restore"
