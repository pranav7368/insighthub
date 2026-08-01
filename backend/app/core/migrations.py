"""Schema migrations.

`db.SCHEMA` is a pile of `CREATE TABLE IF NOT EXISTS`, which is fine for a
database that does not exist yet and does **nothing** for one that does. Adding
a column to an existing table is silently skipped, so a released build meets a
customer's database missing the column it now selects. That is not a
theoretical risk: it was hit twice in one day (`alerts.created_by`,
`column_policies`) while the schema was still young.

This module closes that hole with the smallest thing that actually works:

* every change is an entry in `MIGRATIONS` with a stable `id`;
* applied ids are recorded in `schema_migrations`;
* `run_migrations()` applies the missing ones, in order, once;
* each step is written to be **idempotent anyway** (`ADD COLUMN IF NOT EXISTS`),
  so a half-applied or hand-patched database converges rather than wedging.

Deliberately not Alembic: the app supports two very different backends through
one DuckDB connection (a local file, or Postgres via ATTACH), and Alembic wants
a SQLAlchemy engine we do not have. The ledger below is ~60 lines and runs
identically on both.

**Adding a migration**: append to `MIGRATIONS` with a new id — never edit or
reorder an existing entry, and never renumber. Ids are permanent; a database in
the field has already recorded them.
"""

from dataclasses import dataclass
from typing import Callable

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id          VARCHAR PRIMARY KEY,
    applied_at  TIMESTAMP DEFAULT current_timestamp
);
"""


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    statements: tuple[str, ...] = ()
    # for anything a plain statement list cannot express
    run: Callable | None = None


def _add_column(table: str, column: str, type_sql: str) -> str:
    # Supported by both DuckDB and Postgres, and idempotent on its own.
    return f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type_sql}"


def _add_bool_column(table: str, column: str, default: bool) -> tuple[str, str]:
    """Add a boolean column, then backfill it — never `DEFAULT false` inline.

    DuckDB reaches Postgres through ATTACH, and its binder rejects a boolean
    literal in ALTER TABLE ... DEFAULT: "only constant DEFAULT expressions are
    supported". `INTEGER DEFAULT 0` is accepted, `BOOLEAN DEFAULT false` is
    not. That failed every migration run against Postgres — the file backend
    was fine, so the whole test suite passed while the deployment target the
    deploy guide recommends could not start.

    Adding the column bare and backfilling in a second statement works on
    both. Reading code already COALESCEs these to false, so a NULL between the
    two statements is harmless.
    """
    return (
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} BOOLEAN",
        f"UPDATE {table} SET {column} = {str(default).lower()} WHERE {column} IS NULL",
    )


# ---------------------------------------------------------------------------
# The ledger. Append only. Ids are permanent.
# ---------------------------------------------------------------------------
MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        id="0001_share_links_created_by",
        description="record who created a share link (its row rules scope the link)",
        statements=(_add_column("share_links", "created_by", "VARCHAR"),),
    ),
    Migration(
        id="0002_alerts_created_by",
        description="record who created an alert (its row rules scope the evaluation)",
        statements=(_add_column("alerts", "created_by", "VARCHAR"),),
    ),
    Migration(
        id="0003_rls_and_privacy_tables",
        description="row-level security rules + per-column PII policy",
        statements=(
            """CREATE TABLE IF NOT EXISTS rls_rules (
                   rule_id        VARCHAR PRIMARY KEY,
                   workspace_id   VARCHAR NOT NULL,
                   dataset_id     VARCHAR NOT NULL,
                   user_id        VARCHAR NOT NULL,
                   column_name    VARCHAR NOT NULL,
                   operator       VARCHAR NOT NULL DEFAULT 'in',
                   allowed_values VARCHAR NOT NULL,
                   created_at     TIMESTAMP DEFAULT current_timestamp
               )""",
            """CREATE TABLE IF NOT EXISTS column_policies (
                   dataset_id   VARCHAR NOT NULL,
                   workspace_id VARCHAR NOT NULL,
                   column_name  VARCHAR NOT NULL,
                   pii_kind     VARCHAR,
                   masked       BOOLEAN DEFAULT true,
                   PRIMARY KEY (dataset_id, column_name)
               )""",
        ),
    ),
    Migration(
        id="0004_views_section_order",
        description="saved views remember the order sections are arranged in",
        # config is a JSON blob; older views simply lack the key and the
        # frontend falls back to the natural order. Nothing to alter.
        statements=(),
    ),
    Migration(
        id="0005_user_session_and_lockout",
        description="revocable sessions (token_epoch) + per-account login lockout",
        statements=(
            _add_column("users", "token_epoch", "INTEGER DEFAULT 0"),
            _add_column("users", "failed_logins", "INTEGER DEFAULT 0"),
            _add_column("users", "locked_until", "TIMESTAMP"),
        ),
    ),
    Migration(
        id="0006_mfa",
        description="TOTP second factor + single-use recovery codes",
        statements=(
            _add_column("users", "mfa_secret", "VARCHAR"),
            *_add_bool_column("users", "mfa_enabled", False),
            _add_column("users", "mfa_last_step", "BIGINT"),
            """CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
                   user_id      VARCHAR NOT NULL,
                   workspace_id VARCHAR NOT NULL,
                   code_hash    VARCHAR NOT NULL,
                   created_at   TIMESTAMP DEFAULT current_timestamp
               )""",
        ),
    ),
    Migration(
        id="0007_retention_policies",
        description="per-workspace retention periods (all off by default)",
        statements=(
            """CREATE TABLE IF NOT EXISTS retention_policies (
                   workspace_id VARCHAR PRIMARY KEY,
                   audit_days   INTEGER DEFAULT 0,
                   archive_days INTEGER DEFAULT 0,
                   dataset_days INTEGER DEFAULT 0,
                   updated_at   TIMESTAMP DEFAULT current_timestamp
               )""",
        ),
    ),
    Migration(
        id="0008_workspace_require_mfa",
        description="admins can require a second factor for the whole workspace",
        statements=_add_bool_column("workspaces", "require_mfa", False),
    ),
)


def applied_ids(con) -> set[str]:
    con.execute(_LEDGER)
    return {r[0] for r in con.execute("SELECT id FROM schema_migrations").fetchall()}


def run_migrations(con) -> list[str]:
    """Apply every migration this database has not recorded. Returns the ids
    applied, so callers (and tests) can assert on what happened."""
    done = applied_ids(con)
    newly: list[str] = []
    for migration in MIGRATIONS:
        if migration.id in done:
            continue
        for statement in migration.statements:
            con.execute(statement)
        if migration.run is not None:
            migration.run(con)
        con.execute("INSERT INTO schema_migrations (id) VALUES (?)", [migration.id])
        newly.append(migration.id)
    return newly


def pending_ids(con) -> list[str]:
    done = applied_ids(con)
    return [m.id for m in MIGRATIONS if m.id not in done]
