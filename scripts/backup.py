#!/usr/bin/env python3
"""Back up, verify and restore an InsightHub database.

Works the same whether the deployment stores data in a DuckDB file or in
Postgres, because everything goes through the application's own connection.
That also makes it the migration path between the two: back up from one, set
`IH_DATABASE_URL`, restore into the other.

    python scripts/backup.py create  /backups/insighthub
    python scripts/backup.py verify  /backups/insighthub/2026-08-01T0300
    python scripts/backup.py restore /backups/insighthub/2026-08-01T0300
    python scripts/backup.py prune   /backups/insighthub --keep 14

A nightly cron is the usual arrangement:

    0 3 * * *  cd /srv/insighthub/backend && \\
               ../.venv/bin/python ../scripts/backup.py create /backups/insighthub && \\
               ../.venv/bin/python ../scripts/backup.py prune  /backups/insighthub --keep 14

**Verify on a schedule too.** An archive that cannot be read is worth
discovering on an ordinary Tuesday rather than on the day you need it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core import db                                          # noqa: E402
from app.core.backup import (                                    # noqa: E402
    BackupError, create_backup, prune, restore_backup, verify_backup,
)


def _stamped(root: Path) -> Path:
    return root / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def cmd_create(args) -> int:
    root = Path(args.destination)
    target = _stamped(root) if args.timestamped else root
    manifest = create_backup(db.connect(), target)
    rows = sum(manifest["tables"].values())
    print(f"backed up {len(manifest['tables'])} tables ({rows:,} rows) to {target}")
    return 0


def cmd_verify(args) -> int:
    result = verify_backup(args.source)
    print(f"archive OK — {result['tables']} tables, {result['rows']:,} rows, "
          f"taken {result['created_at']}")
    return 0


def cmd_restore(args) -> int:
    if not args.force:
        print("This replaces the contents of the target database.")
        print(f"  archive: {args.source}")
        print(f"  target:  {'Postgres' if db.config.DATABASE_URL else db.config.DB_PATH}")
        if input("Type 'restore' to continue: ").strip() != "restore":
            print("aborted")
            return 1
    result = restore_backup(db.connect(), args.source, force=True)
    rows = sum(result["restored"].values())
    print(f"restored {len(result['restored'])} tables ({rows:,} rows) "
          f"from an archive taken {result['created_at']}")
    return 0


def cmd_prune(args) -> int:
    removed = prune(args.directory, keep=args.keep)
    print(f"removed {len(removed)} old archive(s); kept the newest {args.keep}")
    for name in removed:
        print(f"  - {name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="write a new archive")
    create.add_argument("destination")
    create.add_argument("--no-timestamp", dest="timestamped", action="store_false",
                        help="write directly into DESTINATION instead of a dated subdirectory")
    create.set_defaults(func=cmd_create, timestamped=True)

    verify = sub.add_parser("verify", help="check an archive is complete and readable")
    verify.add_argument("source")
    verify.set_defaults(func=cmd_verify)

    restore = sub.add_parser("restore", help="restore an archive over the current database")
    restore.add_argument("source")
    restore.add_argument("--force", action="store_true", help="skip the confirmation prompt")
    restore.set_defaults(func=cmd_restore)

    prune_cmd = sub.add_parser("prune", help="delete all but the newest archives")
    prune_cmd.add_argument("directory")
    prune_cmd.add_argument("--keep", type=int, default=14)
    prune_cmd.set_defaults(func=cmd_prune)

    args = parser.parse_args()
    try:
        return args.func(args)
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
