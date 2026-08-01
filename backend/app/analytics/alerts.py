"""Threshold alerts — watch a measure and POST to a webhook when it crosses a
line.

An alert names a measure, an aggregate (total / latest period / month-over-month
%), a comparator, and a threshold. It is evaluated on a schedule; the value is
computed deterministically from the data (never an LLM), and the webhook fires
only on the transition *into* 'firing' (re-arms on return to 'ok') so a lasting
condition doesn't spam. The webhook URL passes the shared SSRF guard, so an
alert can't be used to probe internal services.
"""

import operator

from ..core import config, db, nettrust
from ..core.security import new_id
from ..core.sqlsafe import safe_identifier, safe_table_name
from .engine import get_columns, get_dataset
from .rls import secured_relation

AGGREGATES = ("total", "latest", "mom_pct")
OPS = {"lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge}
_OP_TEXT = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}
MAX_NAME = 120

_SELECT = ("alert_id, dataset_id, name, measure, aggregate, op, threshold, webhook_url, "
           "enabled, last_checked, last_value, last_state, last_error, last_fired_at, created_at, "
           "created_by")


class AlertError(ValueError):
    """An alert could not be created or evaluated."""


class AlertNotFound(AlertError):
    """No such alert in this workspace."""


def _row(r) -> dict:
    return {
        "alert_id": r[0], "dataset_id": r[1], "name": r[2], "measure": r[3],
        "aggregate": r[4], "op": r[5], "threshold": r[6], "webhook_url": r[7],
        "enabled": bool(r[8]),
        "last_checked": str(r[9]) if r[9] is not None else None,
        "last_value": r[10], "last_state": r[11], "last_error": r[12],
        "last_fired_at": str(r[13]) if r[13] is not None else None,
        "created_at": str(r[14]), "created_by": r[15],
    }


def _get_alert(con, workspace_id: str, alert_id: str) -> dict:
    r = con.execute(f"SELECT {_SELECT} FROM alerts WHERE alert_id = ? AND workspace_id = ?",
                    [alert_id, workspace_id]).fetchone()
    if r is None:
        raise AlertNotFound("alert not found")
    return _row(r)


def list_alerts(con, workspace_id: str, dataset_id: str | None = None) -> list[dict]:
    if dataset_id:
        rows = con.execute(f"SELECT {_SELECT} FROM alerts WHERE workspace_id = ? AND dataset_id = ? ORDER BY created_at DESC",
                           [workspace_id, dataset_id]).fetchall()
    else:
        rows = con.execute(f"SELECT {_SELECT} FROM alerts WHERE workspace_id = ? ORDER BY created_at DESC",
                           [workspace_id]).fetchall()
    return [_row(r) for r in rows]


def create_alert(con, workspace_id: str, dataset_id: str, name: str, measure: str,
                 aggregate: str, op: str, threshold, webhook_url: str,
                 created_by: str | None = None) -> dict:
    get_dataset(con, workspace_id, dataset_id)  # DatasetNotFound (→404) for other tenants
    name = (name or "").strip()
    if not name:
        raise AlertError("a name is required")
    if aggregate not in AGGREGATES:
        raise AlertError("invalid aggregate")
    if op not in OPS:
        raise AlertError("invalid comparator")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise AlertError("threshold must be a number")
    if not any(c.name == measure and c.role == "measure" for c in get_columns(con, workspace_id, dataset_id)):
        raise AlertError("choose a numeric measure to watch")
    webhook_url = (webhook_url or "").strip()
    try:
        nettrust.validate_url(webhook_url)
    except nettrust.BlockedURLError as exc:
        raise AlertError(str(exc))

    alert_id = new_id("alert")
    con.execute(
        """INSERT INTO alerts (alert_id, workspace_id, dataset_id, name, measure, aggregate, op, threshold,
                              webhook_url, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [alert_id, workspace_id, dataset_id, name[:MAX_NAME], measure, aggregate, op, threshold,
         webhook_url, created_by],
    )
    return _get_alert(con, workspace_id, alert_id)


def set_enabled(con, workspace_id: str, alert_id: str, enabled: bool) -> dict:
    _get_alert(con, workspace_id, alert_id)  # ensures existence + tenant
    con.execute("UPDATE alerts SET enabled = ? WHERE alert_id = ? AND workspace_id = ?",
                [bool(enabled), alert_id, workspace_id])
    return _get_alert(con, workspace_id, alert_id)


def delete_alert(con, workspace_id: str, alert_id: str) -> int:
    n = con.execute("SELECT count(*) FROM alerts WHERE alert_id = ? AND workspace_id = ?",
                    [alert_id, workspace_id]).fetchone()[0]
    con.execute("DELETE FROM alerts WHERE alert_id = ? AND workspace_id = ?", [alert_id, workspace_id])
    return n


def _compute_value(con, workspace_id: str, dataset_id: str, measure: str, aggregate: str,
                   user_id: str | None = None):
    """Deterministic current value of the watched measure. Returns None when
    there isn't enough data (e.g. mom_pct with a single month).

    Evaluated as the alert's CREATOR: a member restricted to one region must
    not learn workspace-wide totals by pointing an alert at the dataset."""
    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise AlertError("alerts only apply to structured datasets")
    cols = get_columns(con, workspace_id, dataset_id)
    allowed = {c.name for c in cols}
    if not any(c.name == measure and c.role == "measure" for c in cols):
        raise AlertError(f"{measure!r} is not a measure of this dataset")
    tq, rls_params = secured_relation(con, workspace_id, user_id, dataset)
    mq = safe_identifier(measure, allowed)

    if aggregate == "total":
        v = con.execute(f"SELECT sum({mq}) FROM {tq}", list(rls_params)).fetchone()[0]
        return None if v is None else float(v)

    date_col = next((c.name for c in cols if c.role == "date"), None)
    if not date_col:
        raise AlertError("this alert needs a date column")
    dq = safe_identifier(date_col, allowed)
    mexpr = f"strftime(date_trunc('month', TRY_CAST({dq} AS TIMESTAMP)), '%Y-%m')"
    rows = con.execute(
        f"SELECT {mexpr} AS m, sum({mq}) AS v FROM {tq} "
        f"WHERE TRY_CAST({dq} AS TIMESTAMP) IS NOT NULL GROUP BY m ORDER BY m",
        list(rls_params),
    ).fetchall()
    rows = [r for r in rows if r[0] is not None]
    if not rows:
        return None
    if aggregate == "latest":
        v = rows[-1][1]
        return None if v is None else float(v)
    # mom_pct
    if len(rows) < 2:
        return None
    prev, last = rows[-2][1], rows[-1][1]
    if prev in (None, 0) or last is None:
        return None
    return (float(last) - float(prev)) / float(prev) * 100.0


def _message(alert: dict, value: float) -> dict:
    unit = "%" if alert["aggregate"] == "mom_pct" else ""
    pretty = f"{value:,.2f}{unit}"
    what = {"total": "total", "latest": "latest-period", "mom_pct": "month-over-month change of"}[alert["aggregate"]]
    text = (f"🔔 InsightHub alert — {alert['name']}: {what} {alert['measure']} is {pretty} "
            f"(threshold {_OP_TEXT[alert['op']]} {alert['threshold']:g}).")
    return {
        "type": "insighthub.alert",
        "alert": alert["name"],
        "dataset_id": alert["dataset_id"],
        "measure": alert["measure"],
        "aggregate": alert["aggregate"],
        "op": alert["op"],
        "threshold": alert["threshold"],
        "value": value,
        "text": text,      # Slack/Discord/Teams render this field
    }


def _post(alert: dict, payload: dict) -> None:
    nettrust.http_post_json(alert["webhook_url"], payload)


def evaluate_alert(con, workspace_id: str, alert_id: str, deliver: bool = True) -> dict:
    """Evaluate an alert, update its state, and deliver the webhook on a fresh
    transition into 'firing'. Never raises for data/delivery problems — those
    are recorded on the alert row."""
    alert = _get_alert(con, workspace_id, alert_id)
    try:
        value = _compute_value(con, workspace_id, alert["dataset_id"], alert["measure"],
                               alert["aggregate"], alert.get("created_by"))
    except AlertError as exc:
        con.execute("UPDATE alerts SET last_checked = current_timestamp, last_state = 'error', last_error = ? "
                    "WHERE alert_id = ? AND workspace_id = ?", [str(exc)[:400], alert_id, workspace_id])
        return {"state": "error", "error": str(exc), "value": None}

    prev = alert["last_state"]
    if value is None:
        state, fired = "pending", False
    else:
        fired = OPS[alert["op"]](value, alert["threshold"])
        state = "firing" if fired else "ok"

    fired_now = fired and prev != "firing"
    error = None
    if fired_now and deliver and alert["enabled"]:
        try:
            _post(alert, _message(alert, value))
        except (nettrust.BlockedURLError, nettrust.FetchError) as exc:
            error = f"delivery failed: {exc}"

    con.execute(
        "UPDATE alerts SET last_checked = current_timestamp, last_value = ?, last_state = ?, last_error = ?, "
        "last_fired_at = CASE WHEN ? THEN current_timestamp ELSE last_fired_at END "
        "WHERE alert_id = ? AND workspace_id = ?",
        [value, state, error, bool(fired_now and not error), alert_id, workspace_id],
    )
    return {"state": state, "value": value, "fired": fired_now, "error": error}


def send_test(con, workspace_id: str, alert_id: str) -> dict:
    """Post a sample payload to the webhook so the user can confirm delivery."""
    alert = _get_alert(con, workspace_id, alert_id)
    payload = _message(alert, alert["last_value"] if alert["last_value"] is not None else 0.0)
    payload["text"] = f"✅ Test from InsightHub — “{alert['name']}” webhook is connected."
    payload["test"] = True
    try:
        nettrust.http_post_json(alert["webhook_url"], payload)
    except (nettrust.BlockedURLError, nettrust.FetchError) as exc:
        raise AlertError(str(exc))
    return {"ok": True}


def run_due_alerts(con) -> None:
    """Scheduler hook: evaluate every enabled alert (each isolated)."""
    for alert_id, workspace_id in con.execute(
        "SELECT alert_id, workspace_id FROM alerts WHERE enabled = true"
    ).fetchall():
        try:
            evaluate_alert(con, workspace_id, alert_id, deliver=True)
        except Exception:  # never let one bad alert stop the rest
            pass
