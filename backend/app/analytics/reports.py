"""Scheduled email reports — the dashboard's story, delivered.

A schedule names a dataset, a measure, recipients and a frequency (daily,
weekly, monthly). Each send builds one report from numbers the app already
computes — KPIs, what changed and why (the variance waterfall), targets, and
the recommended actions — and renders them as an HTML email with a plain-text
alternative. No LLM writes any of it: every sentence is a template filled with
computed figures, the same rule as the rest of the product.

An email leaves the system, so it is built like a share link: evaluated under
its creator's row rules, PII ALWAYS masked (whoever created it), aggregates
only — never rows. Recipients get one message each, so they do not see each
other's addresses.

Delivery is plain SMTP (stdlib smtplib), configured by IH_SMTP_*; with no
host configured, sending fails with a clear message rather than silently.
"""

import html
import json
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from ..core import config
from ..core.security import new_id
from .actions import recommend
from .drill import DrillError
from .engine import compute_dashboard, get_dataset
from .intelligence import format_value
from .targets import list_targets
from .variance import explain_variance

FREQUENCIES = ("daily", "weekly", "monthly")
MAX_RECIPIENTS = 20
MAX_NAME = 120
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SELECT = ("report_id, dataset_id, name, measure, recipients, frequency, enabled, created_by, "
           "last_sent_at, last_status, last_error, created_at, last_attempt_at")
RETRY_AFTER_SECONDS = 3600      # after a failed send, wait before trying again
_STATUS_LABEL = {"met": "met", "on_track": "on track", "at_risk": "at risk", "off_track": "off track",
                 "missed": "missed", "not_started": "not started"}


class ReportError(ValueError):
    """A report could not be scheduled, built or sent."""


class ReportNotFound(ReportError):
    """No such report in this workspace."""


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _row(r) -> dict:
    return {"report_id": r[0], "dataset_id": r[1], "name": r[2], "measure": r[3],
            "recipients": json.loads(r[4] or "[]"), "frequency": r[5], "enabled": bool(r[6]),
            "created_by": r[7], "last_sent_at": str(r[8]) if r[8] is not None else None,
            "last_status": r[9], "last_error": r[10], "created_at": str(r[11]),
            "last_attempt_at": str(r[12]) if r[12] is not None else None}


def email_configured() -> bool:
    return bool(config.SMTP_HOST)


# ------------------------------------------------------------- schedules --

def _clean_recipients(recipients) -> list[str]:
    if isinstance(recipients, str):
        recipients = re.split(r"[,\s;]+", recipients)
    out = []
    for r in recipients or []:
        r = str(r).strip().lower()
        if not r:
            continue
        if not _EMAIL.match(r) or len(r) > 254:
            raise ReportError(f"{r!r} is not an email address")
        if r not in out:
            out.append(r)
    if not out:
        raise ReportError("add at least one recipient")
    if len(out) > MAX_RECIPIENTS:
        raise ReportError(f"at most {MAX_RECIPIENTS} recipients per report")
    return out


def create_report(con, workspace_id, dataset_id, *, name, recipients, frequency="weekly",
                  measure=None, created_by=None) -> dict:
    dataset = get_dataset(con, workspace_id, dataset_id)      # DatasetNotFound for other tenants
    if dataset["kind"] != "structured":
        raise ReportError("reports apply to spreadsheet datasets")
    name = (name or "").strip()[:MAX_NAME]
    if not name:
        raise ReportError("a name is required")
    if frequency not in FREQUENCIES:
        raise ReportError(f"frequency must be one of {', '.join(FREQUENCIES)}")
    cleaned = _clean_recipients(recipients)
    if measure:
        cols = con.execute("SELECT column_name FROM dataset_columns WHERE dataset_id = ? AND workspace_id = ? "
                           "AND role = 'measure'", [dataset_id, workspace_id]).fetchall()
        if measure not in {c[0] for c in cols}:
            raise ReportError(f"{measure!r} is not a numeric measure")
    report_id = new_id("rpt")
    con.execute(
        """INSERT INTO report_schedules (report_id, workspace_id, dataset_id, name, measure, recipients,
                                         frequency, enabled, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, true, ?)""",
        [report_id, workspace_id, dataset_id, name, measure or None, json.dumps(cleaned), frequency, created_by],
    )
    return get_report(con, workspace_id, report_id)


def get_report(con, workspace_id, report_id) -> dict:
    r = con.execute(f"SELECT {_SELECT} FROM report_schedules WHERE report_id = ? AND workspace_id = ?",
                    [report_id, workspace_id]).fetchone()
    if r is None:
        raise ReportNotFound("report not found")
    return _row(r)


def list_reports(con, workspace_id, dataset_id=None) -> list[dict]:
    sql = f"SELECT {_SELECT} FROM report_schedules WHERE workspace_id = ?"
    params = [workspace_id]
    if dataset_id:
        sql += " AND dataset_id = ?"
        params.append(dataset_id)
    return [_row(r) for r in con.execute(sql + " ORDER BY created_at DESC", params).fetchall()]


def set_report_enabled(con, workspace_id, report_id, enabled: bool) -> dict:
    get_report(con, workspace_id, report_id)
    con.execute("UPDATE report_schedules SET enabled = ? WHERE report_id = ? AND workspace_id = ?",
                [bool(enabled), report_id, workspace_id])
    return get_report(con, workspace_id, report_id)


def delete_report(con, workspace_id, report_id) -> int:
    n = con.execute("SELECT count(*) FROM report_schedules WHERE report_id = ? AND workspace_id = ?",
                    [report_id, workspace_id]).fetchone()[0]
    con.execute("DELETE FROM report_schedules WHERE report_id = ? AND workspace_id = ?", [report_id, workspace_id])
    return n


def is_due(report: dict, now: datetime) -> bool:
    """Calendar-based, so a report goes out once per period however often the
    scheduler ticks: daily -> a new day, weekly -> 7 days on, monthly -> a new
    calendar month."""
    if not report["enabled"]:
        return False
    if report["last_status"] == "error" and report["last_attempt_at"]:
        # a broken mail server must not be retried every scheduler tick
        tried = datetime.fromisoformat(report["last_attempt_at"][:19])
        if (now - tried).total_seconds() < RETRY_AFTER_SECONDS:
            return False
    if not report["last_sent_at"]:
        return True
    last = datetime.fromisoformat(report["last_sent_at"][:19])
    if report["frequency"] == "daily":
        return now.date() > last.date()
    if report["frequency"] == "weekly":
        return (now - last).days >= 7
    return (now.year, now.month) != (last.year, last.month)


# --------------------------------------------------------------- content --

def build_report(con, workspace_id, dataset_id, *, measure=None, user_id=None, name=None) -> dict:
    """{subject, text, html, facts} — every figure computed, every name masked."""
    dash = compute_dashboard(con, workspace_id, dataset_id, breakdown_measure=measure,
                             user_id=user_id, public=True)
    measure = measure if measure in {m["name"] for m in dash["measures"]} else dash["chosen_measure"]
    if not measure:
        raise ReportError("this dataset has no numeric measure to report on")
    sub = {m["name"]: m["subtype"] for m in dash["measures"]}
    fv = lambda m, v: format_value(v, sub.get(m))   # noqa: E731
    dataset_name = dash["dataset"]["name"]

    kpis = []
    for k in dash["kpis"]:
        line = f"{_h(k['column']).capitalize()}: {fv(k['column'], k['total'])} in total"
        if k.get("period_label"):
            line += f"; {fv(k['column'], k['current_period'])} in {k['period_label']}"
            if k.get("delta_pct") is not None:
                line += f" ({k['delta_pct']:+.1f}% on the month before)"
        kpis.append(line)

    change, change_lines, sig_line = None, [], None
    if dash.get("date_column"):
        try:
            change = explain_variance(con, workspace_id, dataset_id, measure=measure, user_id=user_id,
                                      public=True, limit=5)
        except DrillError:
            change = None
    if change:
        for s in change["steps"][:5]:
            if s["delta"]:
                who = "(blank)" if s["blank"] else str(s["name"])
                change_lines.append(f"{who}: {'+' if s['delta'] > 0 else '−'}{fv(measure, abs(s['delta']))}")
        sig = change.get("significance")
        if sig:
            sig_line = {"normal": "Within this series' normal month-to-month variation.",
                        "notable": f"A notable move: {abs(sig['z']):.1f}× the typical swing.",
                        "unusual": f"An unusual move: {abs(sig['z']):.1f}× the typical swing."}[sig["level"]]

    targets = [t for t in list_targets(con, workspace_id, dataset_id, user_id)
               if t.get("current") and t.get("status") not in ("broken",)]
    target_lines = [
        f"{_h(t['measure'])} {t['period']}" + (f" ({', '.join(f'{k} {v}' for k, v in t['filters'].items())})"
                                                if t["filters"] else "")
        + f": {fv(t['measure'], t['actual'])} of {fv(t['measure'], t['value'])} — "
        f"{_STATUS_LABEL.get(t['status'], t['status'])}, on pace for {fv(t['measure'], t['projection'])}"
        for t in targets
    ]

    try:
        actions = recommend(con, workspace_id, dataset_id, measure=measure, user_id=user_id,
                            public=True, limit=5)["actions"]
    except DrillError:
        actions = []

    title = name or f"{dataset_name} report"
    headline = change["summary"] if change else f"{_h(measure).capitalize()} report for {dataset_name}."
    subject = f"{title}: {headline}"[:180]

    sections = [("Headline", [headline] + ([sig_line] if sig_line else []) +
                 ([change["note"]] if change and change.get("note") else []))]
    sections.append(("Key numbers", kpis))
    if change_lines:
        sections.append((f"Where the change came from (by {change['dimension'].replace('_', ' ')})", change_lines))
    if target_lines:
        sections.append(("Targets", target_lines))
    if actions:
        sections.append(("Recommended actions", [f"{a['title']}. {a['why']} → {a['action']}" for a in actions]))

    footer = ("Every figure above was computed directly from your data; names that could identify a "
              "person are masked in emailed reports.")
    link = config.APP_URL.rstrip("/") + f"/?ds={dataset_id}" if config.APP_URL else None
    text = "\n\n".join([title] + [f"{h}\n" + "\n".join(f"- {x}" for x in items) for h, items in sections]
                       + ([f"Open the dashboard: {link}"] if link else []) + [footer])
    html_body = _html(title, sections, link, footer)
    return {"subject": subject, "text": text, "html": html_body,
            "facts": {"measure": measure, "kpis": kpis, "change": change_lines, "targets": target_lines,
                      "actions": [a["id"] for a in actions]}}


def _h(name: str) -> str:
    return (name or "").replace("_", " ")


def _html(title, sections, link, footer) -> str:
    e = html.escape
    parts = [
        '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto;color:#0b0b0b">',
        f'<h2 style="margin:0 0 4px;font-size:20px">{e(title)}</h2>',
    ]
    for heading, items in sections:
        parts.append(f'<h3 style="margin:20px 0 6px;font-size:13px;text-transform:uppercase;'
                     f'letter-spacing:.04em;color:#52514e">{e(heading)}</h3>')
        parts.append('<ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.55">')
        parts.extend(f"<li>{e(item)}</li>" for item in items)
        parts.append("</ul>")
    if link:
        parts.append(f'<p style="margin:22px 0"><a href="{e(link)}" style="background:#2a6fc4;color:#fff;'
                     f'padding:9px 14px;border-radius:8px;text-decoration:none;font-size:14px">'
                     f'Open the dashboard</a></p>')
    parts.append(f'<p style="margin-top:24px;font-size:12px;color:#6f6e69">{e(footer)}</p></div>')
    return "".join(parts)


# -------------------------------------------------------------- delivery --

def _send(subject: str, text: str, html_body: str, recipients: list[str]) -> None:
    if not email_configured():
        raise ReportError("email is not configured on this server (set IH_SMTP_HOST)")
    smtp_cls = smtplib.SMTP_SSL if config.SMTP_SSL else smtplib.SMTP
    with smtp_cls(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT) as smtp:
        if config.SMTP_STARTTLS and not config.SMTP_SSL:
            smtp.starttls()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        for rcpt in recipients:        # one message each: recipients never see each other
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = config.SMTP_FROM
            msg["To"] = rcpt
            msg.set_content(text)
            msg.add_alternative(html_body, subtype="html")
            smtp.send_message(msg)


def send_report(con, workspace_id, report_id, now: datetime | None = None) -> dict:
    """Build and send now; the outcome is recorded on the schedule either way."""
    report = get_report(con, workspace_id, report_id)
    now = now or _now()
    try:
        built = build_report(con, workspace_id, report["dataset_id"], measure=report["measure"],
                             user_id=report["created_by"], name=report["name"])
        _send(built["subject"], built["text"], built["html"], report["recipients"])
    except (ReportError, DrillError, smtplib.SMTPException, OSError) as exc:
        con.execute("UPDATE report_schedules SET last_status = 'error', last_error = ?, last_attempt_at = ? "
                    "WHERE report_id = ? AND workspace_id = ?", [str(exc)[:400], now, report_id, workspace_id])
        raise ReportError(str(exc)) from exc
    con.execute("UPDATE report_schedules SET last_sent_at = ?, last_attempt_at = ?, last_status = 'sent', "
                "last_error = NULL WHERE report_id = ? AND workspace_id = ?", [now, now, report_id, workspace_id])
    return {"sent": len(report["recipients"]), "subject": built["subject"]}


def run_due_reports(con, now: datetime | None = None) -> list[str]:
    """Scheduler hook: send every enabled report that is due (each isolated)."""
    now = now or _now()
    sent = []
    for (workspace_id,) in con.execute("SELECT DISTINCT workspace_id FROM report_schedules WHERE enabled = true"
                                       ).fetchall():
        for report in list_reports(con, workspace_id):
            if not is_due(report, now):
                continue
            try:
                send_report(con, workspace_id, report["report_id"], now)
                sent.append(report["report_id"])
            except ReportError:
                pass        # recorded on the row; one bad report never stops the rest
    return sent
