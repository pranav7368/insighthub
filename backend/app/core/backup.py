"""Backup and restore.

`docs/SECURITY.md` listed "no automated backup or tested restore" as a known
gap. The second half is the one that bites: almost everyone has backups, and
the ones who lose data are the ones who never tried restoring. So the point of
this module is not that it writes files — it is that `test_backup.py` performs
a **full round trip** (real data in, back up, wipe, restore, compare) on every
CI run, so "we can restore" is a tested claim rather than a hope.

Design notes:

* **Backend-agnostic by construction.** Everything goes through the app's own
  DuckDB connection, which is either a local file or a Postgres catalog
  reached through ATTACH. One code path covers both, and the archive taken from
  one restores into the other — which is also the migration path from the
  single-file evaluation setup to a Postgres deployment.
* **Parquet, not SQL dumps.** Types survive, files are small, and the archive
  is readable by anything if this tool ever disappears. A backup you can only
  restore with our code is a hostage, not a backup.
* **The manifest records the schema version.** Restoring an archive taken from a
  *newer* build into an older one would half-fit and silently corrupt, so it is
  refused outright.
* **Restore refuses to overwrite by default.** Data loss during a restore is a
  particularly bitter way to lose data.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .migrations import MIGRATIONS, applied_ids, run_migrations
from .sqlsafe import safe_table_name

FORMAT_VERSION = 1
MANIFEST = "manifest.json"


class BackupError(Exception):
    """A backup could not be written, or an archive could not be restored."""


def _tables(con) -> list[str]:
    """Every table in the current catalog, metadata and per-dataset alike."""
    rows = con.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
           ORDER BY table_name"""
    ).fetchall()
    return [r[0] for r in rows]


def _schema_tables() -> set[str]:
    """Tables the application schema creates, as opposed to the per-dataset
    raw tables, which are created on upload and must be recreated on restore."""
    import re

    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db.SCHEMA))


# --------------------------------------------------------------- backup ---

def create_backup(con, destination: str | Path) -> dict:
    """Write every table to `destination` as Parquet, plus a manifest."""
    dest = Path(destination)
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"{dest} is not empty — refusing to overwrite an existing archive")
    dest.mkdir(parents=True, exist_ok=True)

    tables = _tables(con)
    counts: dict[str, int] = {}
    for table in tables:
        quoted = safe_table_name(table)
        target = (dest / f"{table}.parquet").as_posix().replace("'", "''")
        con.execute(f"COPY (SELECT * FROM {quoted}) TO '{target}' (FORMAT PARQUET)")
        counts[table] = con.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]

    manifest = {
        "format": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # so a newer archive is never half-restored into an older build
        "schema_migrations": sorted(applied_ids(con)),
        "known_migrations": [m.id for m in MIGRATIONS],
        "tables": counts,
    }
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def read_manifest(source: str | Path) -> dict:
    path = Path(source) / MANIFEST
    if not path.exists():
        raise BackupError(f"{source} does not look like a backup (no {MANIFEST})")
    return json.loads(path.read_text(encoding="utf-8"))


# -------------------------------------------------------------- restore ---

def _is_empty(con) -> bool:
    for table in ("workspaces", "users", "datasets"):
        try:
            if con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
                return False
        except Exception:      # noqa: BLE001 — table absent means empty enough
            continue
    return True


def restore_backup(con, source: str | Path, force: bool = False) -> dict:
    """Restore an archive into `con`. Refuses to overwrite unless `force`."""
    src = Path(source)
    manifest = read_manifest(src)

    if manifest.get("format") != FORMAT_VERSION:
        raise BackupError(
            f"archive format {manifest.get('format')} cannot be read by this build "
            f"(expects {FORMAT_VERSION})"
        )

    # An archive from a newer build carries migrations this code does not know.
    # Restoring it would half-fit: tables present, columns missing.
    unknown = set(manifest.get("schema_migrations", [])) - {m.id for m in MIGRATIONS}
    if unknown:
        raise BackupError(
            "this archive was taken from a newer version of InsightHub "
            f"(unknown migrations: {sorted(unknown)}). Upgrade before restoring."
        )

    if not force and not _is_empty(con):
        raise BackupError(
            "target database already contains data — pass force=True to overwrite it"
        )

    con.execute(db.SCHEMA)
    run_migrations(con)

    schema_tables = _schema_tables()
    restored: dict[str, int] = {}
    for table in manifest["tables"]:
        parquet = src / f"{table}.parquet"
        if not parquet.exists():
            raise BackupError(f"archive is incomplete: {parquet.name} is missing")
        path = parquet.as_posix().replace("'", "''")
        quoted = safe_table_name(table)

        if table in schema_tables or table == "schema_migrations":
            con.execute(f"DELETE FROM {quoted}")
            con.execute(f"INSERT INTO {quoted} SELECT * FROM read_parquet('{path}')")
        else:
            # a per-dataset raw table: recreate it from the archive's own shape
            con.execute(f"DROP TABLE IF EXISTS {quoted}")
            con.execute(f"CREATE TABLE {quoted} AS SELECT * FROM read_parquet('{path}')")
        restored[table] = con.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]

    mismatched = {t: (manifest["tables"][t], restored[t])
                  for t in restored if manifest["tables"][t] != restored[t]}
    if mismatched:
        raise BackupError(f"restore verification failed, expected vs actual: {mismatched}")

    return {"restored": restored, "created_at": manifest["created_at"]}


def verify_backup(source: str | Path) -> dict:
    """Check an archive is complete and readable, without restoring it.

    Worth running on a schedule: an archive that cannot be read is discovered
    either here, or on the worst day of the year.
    """
    src = Path(source)
    manifest = read_manifest(src)
    missing = [t for t in manifest["tables"] if not (src / f"{t}.parquet").exists()]
    if missing:
        raise BackupError(f"archive is incomplete, missing: {missing}")

    import duckdb

    probe = duckdb.connect(":memory:")
    unreadable = []
    for table in manifest["tables"]:
        path = (src / f"{table}.parquet").as_posix().replace("'", "''")
        try:
            rows = probe.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
            if rows != manifest["tables"][table]:
                unreadable.append(f"{table} (expected {manifest['tables'][table]}, found {rows})")
        except Exception as exc:            # noqa: BLE001
            unreadable.append(f"{table} ({exc})")
    probe.close()
    if unreadable:
        raise BackupError(f"archive is damaged: {unreadable}")

    return {"ok": True, "tables": len(manifest["tables"]),
            "rows": sum(manifest["tables"].values()), "created_at": manifest["created_at"]}


def prune(directory: str | Path, keep: int) -> list[str]:
    """Delete all but the newest `keep` archives in a directory."""
    if keep < 1:
        raise BackupError("keep must be at least 1 — pruning every backup is not a policy")
    root = Path(directory)
    archives = sorted(
        (p for p in root.iterdir() if p.is_dir() and (p / MANIFEST).exists()),
        key=lambda p: json.loads((p / MANIFEST).read_text(encoding="utf-8"))["created_at"],
        reverse=True,
    )
    removed = []
    for old in archives[keep:]:
        shutil.rmtree(old)
        removed.append(old.name)
    return removed
