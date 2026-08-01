"""Retention: expiring data on a schedule, per workspace.

DPDP requires a retention period to be *stated and honoured*, and GDPR's
storage-limitation principle wants the same. Until now nothing ever expired, so
no honest retention claim could be made at all.

This is the most dangerous code in the repository — it deletes customer data
without a human present — so it is built defensively:

* **Off by default, everywhere.** `0` means keep forever. A workspace that
  never configures retention is never touched. Silent deletion because someone
  shipped a default would be unrecoverable.
* **A floor on every period.** `MIN_DAYS` stops a mistyped `1` from erasing a
  year of history the same night.
* **Preview before enable.** `preview()` reports exactly what a sweep would
  remove, so an admin sees the blast radius first. The API defaults to preview;
  deleting takes a separate, explicit call.
* **Uploaded data is a separate, louder switch.** Audit entries and rollback
  archives ageing out is routine housekeeping. Deleting the datasets a customer
  uploaded is not, so it has its own setting, its own higher floor, and is
  ignored unless explicitly set.
* **Audit entries are written before the sweep, not after.** A sweep that
  prunes the audit log must not erase the record of itself.

The sweep is idempotent: running it twice deletes nothing the second time.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

from .sqlsafe import safe_table_name

# Nothing expires unless an admin sets a period.
OFF = 0
# A mistyped "1" must not wipe a year of history overnight.
MIN_DAYS = 7
# Uploaded data is the customer's actual work; give it a longer floor.
MIN_DATASET_DAYS = 30


class RetentionError(ValueError):
    """A retention policy was rejected."""


@dataclass(frozen=True)
class Policy:
    """Days to keep each category. 0 = keep forever."""
    audit_days: int = OFF
    archive_days: int = OFF          # rollback snapshots of replaced rows
    dataset_days: int = OFF          # the uploaded data itself

    def as_dict(self) -> dict:
        return asdict(self)


def _validate(days: int, floor: int, label: str) -> int:
    try:
        days = int(days)
    except (TypeError, ValueError, OverflowError):
        # OverflowError matters: int(float('inf')) raises it, and a policy of
        # "infinity days" must be refused rather than crash the endpoint
        raise RetentionError(f"{label} must be a whole number of days")
    if days < 0:
        raise RetentionError(f"{label} cannot be negative")
    if days != OFF and days < floor:
        raise RetentionError(
            f"{label} must be at least {floor} days (or 0 to keep everything). "
            "A very short period deletes history the same night it is set."
        )
    return days


def validate_policy(audit_days=OFF, archive_days=OFF, dataset_days=OFF) -> Policy:
    return Policy(
        audit_days=_validate(audit_days, MIN_DAYS, "audit retention"),
        archive_days=_validate(archive_days, MIN_DAYS, "archive retention"),
        dataset_days=_validate(dataset_days, MIN_DATASET_DAYS, "uploaded-data retention"),
    )


# ------------------------------------------------------------- storage ----

def get_policy(con, workspace_id: str) -> Policy:
    row = con.execute(
        """SELECT audit_days, archive_days, dataset_days FROM retention_policies
           WHERE workspace_id = ?""",
        [workspace_id],
    ).fetchone()
    if row is None:
        return Policy()
    return Policy(int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))


def set_policy(con, workspace_id: str, policy: Policy) -> Policy:
    con.execute("DELETE FROM retention_policies WHERE workspace_id = ?", [workspace_id])
    con.execute(
        """INSERT INTO retention_policies
           (workspace_id, audit_days, archive_days, dataset_days, updated_at)
           VALUES (?, ?, ?, ?, current_timestamp)""",
        [workspace_id, policy.audit_days, policy.archive_days, policy.dataset_days],
    )
    return get_policy(con, workspace_id)


def _cutoff(days: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=days)).replace(tzinfo=None)


# -------------------------------------------------------------- sweeping --

def preview(con, workspace_id: str, now: datetime | None = None) -> dict:
    """What a sweep would remove, without removing anything.

    An admin should always be able to see the blast radius before arming this.
    """
    policy = get_policy(con, workspace_id)
    report = {"policy": policy.as_dict(), "audit_entries": 0,
              "archived_rows": 0, "datasets": []}

    if policy.audit_days:
        report["audit_entries"] = con.execute(
            "SELECT count(*) FROM audit_log WHERE workspace_id = ? AND ts < ?",
            [workspace_id, _cutoff(policy.audit_days, now)],
        ).fetchone()[0]

    if policy.archive_days:
        report["archived_rows"] = con.execute(
            """SELECT count(*) FROM row_archive
               WHERE workspace_id = ? AND batch_id IN (
                   SELECT batch_id FROM ingest_batches
                   WHERE workspace_id = ? AND created_at < ?)""",
            [workspace_id, workspace_id, _cutoff(policy.archive_days, now)],
        ).fetchone()[0]

    if policy.dataset_days:
        report["datasets"] = [
            {"dataset_id": r[0], "name": r[1], "ingested_at": str(r[2])}
            for r in con.execute(
                """SELECT dataset_id, name, ingested_at FROM datasets
                   WHERE workspace_id = ? AND ingested_at < ?""",
                [workspace_id, _cutoff(policy.dataset_days, now)],
            ).fetchall()
        ]
    return report


def sweep(con, workspace_id: str, now: datetime | None = None,
          audit_actor: str = "retention") -> dict:
    """Apply the policy. Returns what was removed.

    Idempotent: a second run finds nothing left to do.
    """
    policy = get_policy(con, workspace_id)
    removed = {"audit_entries": 0, "archived_rows": 0, "datasets": []}
    if not (policy.audit_days or policy.archive_days or policy.dataset_days):
        return removed

    planned = preview(con, workspace_id, now)
    # Record the sweep BEFORE pruning the audit log, or it erases its own trace.
    if any((planned["audit_entries"], planned["archived_rows"], planned["datasets"])):
        con.execute(
            """INSERT INTO audit_log (workspace_id, user_id, action, detail)
               VALUES (?, ?, 'retention_sweep', ?)""",
            [workspace_id, audit_actor,
             f"audit={planned['audit_entries']} archive={planned['archived_rows']} "
             f"datasets={len(planned['datasets'])}"],
        )

    # Datasets first: dropping a dataset also removes its own rows from the
    # tables below, so doing it first keeps the counts from double-reporting.
    for dataset in planned["datasets"]:
        _drop_dataset(con, workspace_id, dataset["dataset_id"])
        removed["datasets"].append(dataset)

    if policy.archive_days:
        cutoff = _cutoff(policy.archive_days, now)
        removed["archived_rows"] = con.execute(
            """SELECT count(*) FROM row_archive
               WHERE workspace_id = ? AND batch_id IN (
                   SELECT batch_id FROM ingest_batches
                   WHERE workspace_id = ? AND created_at < ?)""",
            [workspace_id, workspace_id, cutoff],
        ).fetchone()[0]
        con.execute(
            """DELETE FROM row_archive
               WHERE workspace_id = ? AND batch_id IN (
                   SELECT batch_id FROM ingest_batches
                   WHERE workspace_id = ? AND created_at < ?)""",
            [workspace_id, workspace_id, cutoff],
        )

    if policy.audit_days:
        cutoff = _cutoff(policy.audit_days, now)
        removed["audit_entries"] = con.execute(
            "SELECT count(*) FROM audit_log WHERE workspace_id = ? AND ts < ?",
            [workspace_id, cutoff],
        ).fetchone()[0]
        con.execute("DELETE FROM audit_log WHERE workspace_id = ? AND ts < ?",
                    [workspace_id, cutoff])

    return removed


def _drop_dataset(con, workspace_id: str, dataset_id: str) -> None:
    """Remove a dataset and everything attached to it, physical table included."""
    row = con.execute(
        "SELECT table_name FROM datasets WHERE dataset_id = ? AND workspace_id = ?",
        [dataset_id, workspace_id],
    ).fetchone()
    if row and row[0]:
        con.execute(f"DROP TABLE IF EXISTS {safe_table_name(row[0])}")

    # chunk_embeddings hangs off chunks, not off the dataset, so it has to go
    # first and by chunk_id — deleting chunks before it would orphan the rows
    con.execute(
        """DELETE FROM chunk_embeddings
           WHERE workspace_id = ? AND chunk_id IN (
               SELECT chunk_id FROM chunks WHERE workspace_id = ? AND dataset_id = ?)""",
        [workspace_id, workspace_id, dataset_id],
    )
    for table in ("dataset_columns", "chunks", "ingest_batches", "row_archive",
                  "dashboard_views", "share_links", "alerts", "metrics",
                  "rls_rules", "column_policies", "datasets"):
        con.execute(f"DELETE FROM {table} WHERE workspace_id = ? AND dataset_id = ?",
                    [workspace_id, dataset_id])


def sweep_all(con, now: datetime | None = None) -> dict:
    """Sweep every workspace that has configured a policy. Called by the
    scheduler; each workspace is isolated so one failure cannot stop the rest."""
    results = {}
    rows = con.execute(
        """SELECT workspace_id FROM retention_policies
           WHERE audit_days > 0 OR archive_days > 0 OR dataset_days > 0"""
    ).fetchall()
    for (workspace_id,) in rows:
        try:
            results[workspace_id] = sweep(con, workspace_id, now)
        except Exception as exc:                      # noqa: BLE001
            results[workspace_id] = {"error": str(exc)}
    return results
