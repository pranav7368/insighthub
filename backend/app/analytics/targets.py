"""Targets — "are we going to make the number?"

A target is a value a measure should reach in one period (a month, quarter,
year, week or day), optionally for one segment (`{"region": "North"}`).
Evaluating one is arithmetic over the member's secured rows:

  * actual       — the measure's total in the period so far
  * projection   — the run rate: actual / days elapsed x days in the period.
                   Deliberately the simplest projection there is, so anyone
                   can check it with a calculator; the forecast chart is where
                   the modelled outlook lives.
  * status       — met / on_track / at_risk (projected >= 90%) / off_track
  * needed_per_day — what the remaining days must average to close the gap

"Days elapsed" ends at the dataset's last date, not today: a file uploaded
on the 20th describes the month up to its own last row.
"""

import json
import re
from datetime import date, timedelta

from ..core.security import new_id
from ..core.sqlsafe import safe_identifier
from .drill import DrillError, _date_bounds, _open, period_bounds

GRAINS = ("day", "week", "month", "quarter", "year")
_PERIOD_RE = {
    "day": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "week": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "month": re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"),
    "quarter": re.compile(r"^\d{4}-Q[1-4]$"),
    "year": re.compile(r"^\d{4}$"),
}
AT_RISK = 0.9
MAX_TARGETS_PER_DATASET = 500

_SELECT = "target_id, dataset_id, measure, grain, period, value, filters, created_by, created_at"


class TargetError(ValueError):
    """A target could not be set or evaluated."""


class TargetNotFound(TargetError):
    """No such target in this workspace."""


def _row(r) -> dict:
    return {"target_id": r[0], "dataset_id": r[1], "measure": r[2], "grain": r[3], "period": r[4],
            "value": float(r[5]), "filters": json.loads(r[6] or "{}"), "created_by": r[7],
            "created_at": str(r[8])}


def _bounds(grain: str, period: str) -> tuple[date, date]:
    if grain not in GRAINS:
        raise TargetError(f"unknown period type {grain!r}")
    if not _PERIOD_RE[grain].match(str(period)):
        raise TargetError(f"{period!r} is not a valid {grain}")
    try:
        lo, hi = period_bounds(period, grain)
        start = date.fromisoformat(lo if len(lo) == 10 else f"{lo}-01")
        end_excl = date.fromisoformat(_date_bounds(None, hi)[1][:10])
    except ValueError:
        raise TargetError(f"{period!r} is not a valid {grain}")
    if grain == "week" and start.weekday() != 0:
        raise TargetError("a week target starts on a Monday")
    return start, end_excl - timedelta(days=1)


def set_target(con, workspace_id, dataset_id, *, measure, grain, period, value, filters=None,
               user_id=None) -> dict:
    """Create the target, or replace the one already set for the same
    measure, period and segment — there is only ever one number to hit."""
    sl = _open(con, workspace_id, dataset_id, None, filters, None, None)
    if measure not in sl.measures:
        raise TargetError(f"{measure!r} is not a numeric measure")
    _bounds(grain, period)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise TargetError("the target must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise TargetError("the target must be a finite number")
    fjson = json.dumps(sl.filters, sort_keys=True)

    existing = con.execute(
        """SELECT target_id FROM targets WHERE workspace_id = ? AND dataset_id = ? AND measure = ?
           AND grain = ? AND period = ? AND filters = ?""",
        [workspace_id, dataset_id, measure, grain, period, fjson],
    ).fetchone()
    if existing:
        con.execute("UPDATE targets SET value = ?, created_by = ? WHERE target_id = ? AND workspace_id = ?",
                    [value, user_id, existing[0], workspace_id])
        target_id = existing[0]
    else:
        count = con.execute("SELECT count(*) FROM targets WHERE workspace_id = ? AND dataset_id = ?",
                            [workspace_id, dataset_id]).fetchone()[0]
        if count >= MAX_TARGETS_PER_DATASET:
            raise TargetError("too many targets on this dataset")
        target_id = new_id("tgt")
        con.execute(
            """INSERT INTO targets (target_id, workspace_id, dataset_id, measure, grain, period, value,
                                    filters, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [target_id, workspace_id, dataset_id, measure, grain, period, value, fjson, user_id],
        )
    row = con.execute(f"SELECT {_SELECT} FROM targets WHERE target_id = ? AND workspace_id = ?",
                      [target_id, workspace_id]).fetchone()
    return _row(row)


def delete_target(con, workspace_id, target_id) -> int:
    n = con.execute("SELECT count(*) FROM targets WHERE target_id = ? AND workspace_id = ?",
                    [target_id, workspace_id]).fetchone()[0]
    con.execute("DELETE FROM targets WHERE target_id = ? AND workspace_id = ?", [target_id, workspace_id])
    return n


def evaluate(con, workspace_id, dataset_id, target: dict, user_id=None) -> dict:
    sl = _open(con, workspace_id, dataset_id, user_id, target["filters"], None, None)
    if target["measure"] not in sl.measures:
        return {**target, "status": "broken", "reason": "the measure no longer exists"}
    if not sl.date_col:
        return {**target, "status": "broken", "reason": "the dataset has no date column"}
    start, end = _bounds(target["grain"], target["period"])
    dq = safe_identifier(sl.date_col, sl.allowed)
    mq = safe_identifier(target["measure"], sl.allowed)
    data_end = con.execute(f"SELECT MAX(TRY_CAST({dq} AS TIMESTAMP)) FROM {sl.relation}",
                           list(sl.rls_params)).fetchone()[0]
    data_end = date.fromisoformat(str(data_end)[:10]) if data_end is not None else None

    lo, _ = _date_bounds(start.isoformat(), None)
    _, hi = _date_bounds(None, end.isoformat())
    where, params, _ = sl.where(f"TRY_CAST({dq} AS TIMESTAMP) >= ? AND TRY_CAST({dq} AS TIMESTAMP) < ?",
                                dates=False)
    actual = con.execute(f"SELECT SUM({mq}) FROM {sl.relation} {where}", params + [lo, hi]).fetchone()[0]
    actual = float(actual or 0)

    days = (end - start).days + 1
    if data_end is None or data_end < start:
        elapsed = 0
    else:
        elapsed = min(days, (data_end - start).days + 1)
    remaining = days - elapsed
    projection = actual if remaining == 0 or elapsed == 0 else actual / elapsed * days
    goal = target["value"]
    if elapsed == 0:
        status = "not_started"
    elif actual >= goal and goal >= 0:
        status = "met"
    elif projection >= goal:
        status = "on_track"
    elif goal and projection >= goal * AT_RISK:
        status = "at_risk"
    else:
        status = "off_track"
    if remaining == 0 and status in ("on_track", "at_risk", "off_track"):
        status = "missed"
    return {
        **target,
        "from": start.isoformat(), "to": end.isoformat(),
        "actual": actual, "projection": projection,
        "progress": (actual / goal) if goal else None,
        "projected_ratio": (projection / goal) if goal else None,
        "gap": projection - goal,
        "days": days, "days_elapsed": elapsed, "days_remaining": remaining,
        "needed_per_day": ((goal - actual) / remaining) if remaining > 0 and goal > actual else 0.0,
        "current": data_end is not None and start <= data_end <= end,
        "status": status,
        "subtype": sl.measures.get(target["measure"]),
    }


def list_targets(con, workspace_id, dataset_id, user_id=None, evaluate_all=True) -> list[dict]:
    rows = con.execute(
        f"SELECT {_SELECT} FROM targets WHERE workspace_id = ? AND dataset_id = ? ORDER BY period DESC, measure",
        [workspace_id, dataset_id],
    ).fetchall()
    targets = [_row(r) for r in rows]
    if not evaluate_all:
        return targets
    out = []
    for t in targets:
        try:
            out.append(evaluate(con, workspace_id, dataset_id, t, user_id))
        except (DrillError, TargetError) as exc:   # e.g. a filter column was renamed away
            out.append({**t, "status": "broken", "reason": str(exc)})
    return out
