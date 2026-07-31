"""Public share links — a revocable, read-only dashboard link.

A share link is an unguessable capability token (192 bits) that grants public,
unauthenticated, READ-ONLY access to exactly one dataset's dashboard,
optionally pinned to a saved view. It can carry an expiry and be revoked at any
time.

`resolve_share` is the only function in the codebase that looks up data without
a workspace_id — by design: the token *is* the capability, and it names a
single dataset. Everything else (create/list/revoke) is workspace-scoped and
admin-gated at the API layer, exactly like the rest of the app.
"""

import secrets
from datetime import datetime, timedelta, timezone

from .engine import get_dataset
from .views import ViewNotFound, _get_view

MAX_EXPIRY_DAYS = 366
_SELECT = "token, dataset_id, view_id, label, expires_at, revoked, created_at"


class ShareError(ValueError):
    """A share link could not be created (bad dataset/view/expiry)."""


class ShareNotFound(ShareError):
    """No such share link, or it is revoked/expired."""


def _utcnow_naive() -> datetime:
    # DuckDB TIMESTAMP is tz-naive; keep everything in naive-UTC so comparisons line up
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _row(r) -> dict:
    return {
        "token": r[0], "dataset_id": r[1], "view_id": r[2], "label": r[3],
        "expires_at": str(r[4]) if r[4] is not None else None,
        "revoked": bool(r[5]), "created_at": str(r[6]),
        "path": f"/share/{r[0]}",
    }


def _get_share(con, workspace_id: str, token: str) -> dict:
    r = con.execute(
        f"SELECT {_SELECT} FROM share_links WHERE token = ? AND workspace_id = ?",
        [token, workspace_id],
    ).fetchone()
    if r is None:
        raise ShareNotFound("share link not found")
    return _row(r)


def create_share(con, workspace_id: str, dataset_id: str, view_id: str | None = None,
                 label: str | None = None, expires_in_days: int | None = None,
                 created_by: str | None = None) -> dict:
    get_dataset(con, workspace_id, dataset_id)  # raises DatasetNotFound (→404) for other tenants
    if view_id:
        v = _get_view(con, workspace_id, view_id)  # ViewNotFound for other tenants / bad id
        if v["dataset_id"] != dataset_id:
            raise ShareError("that view belongs to a different dataset")

    expires_at = None
    if expires_in_days:
        try:
            days = int(expires_in_days)
        except (TypeError, ValueError):
            raise ShareError("invalid expiry")
        if days > 0:
            expires_at = _utcnow_naive() + timedelta(days=min(days, MAX_EXPIRY_DAYS))

    token = secrets.token_urlsafe(24)
    con.execute(
        """INSERT INTO share_links
           (token, workspace_id, dataset_id, view_id, label, created_by, expires_at, revoked)
           VALUES (?, ?, ?, ?, ?, ?, ?, false)""",
        [token, workspace_id, dataset_id, view_id, (label or None), created_by, expires_at],
    )
    return _get_share(con, workspace_id, token)


def list_shares(con, workspace_id: str, dataset_id: str | None = None) -> list[dict]:
    if dataset_id:
        rows = con.execute(
            f"SELECT {_SELECT} FROM share_links WHERE workspace_id = ? AND dataset_id = ? ORDER BY created_at DESC",
            [workspace_id, dataset_id],
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {_SELECT} FROM share_links WHERE workspace_id = ? ORDER BY created_at DESC",
            [workspace_id],
        ).fetchall()
    return [_row(r) for r in rows]


def revoke_share(con, workspace_id: str, token: str) -> int:
    n = con.execute(
        "SELECT count(*) FROM share_links WHERE token = ? AND workspace_id = ?",
        [token, workspace_id],
    ).fetchone()[0]
    con.execute("UPDATE share_links SET revoked = true WHERE token = ? AND workspace_id = ?",
                [token, workspace_id])
    return n


def resolve_share(con, token: str) -> dict:
    """PUBLIC lookup: {workspace_id, dataset_id, view_id} for a valid token, or
    raise ShareNotFound if it is missing, revoked, or expired."""
    r = con.execute(
        "SELECT workspace_id, dataset_id, view_id, revoked, expires_at FROM share_links WHERE token = ?",
        [token],
    ).fetchone()
    if r is None or r[3]:  # missing or revoked
        raise ShareNotFound("share link not found")
    if r[4] is not None and r[4] <= _utcnow_naive():
        raise ShareNotFound("share link has expired")
    return {"workspace_id": r[0], "dataset_id": r[1], "view_id": r[2]}


def resolve_share_dashboard_config(con, token: str):
    """PUBLIC: (workspace_id, dataset_id, view_config) for a valid token. The
    pinned view's config (filters/date/measure/hidden_sections) is returned so
    the public dashboard renders exactly what was shared."""
    share = resolve_share(con, token)
    cfg: dict = {}
    if share["view_id"]:
        try:
            cfg = _get_view(con, share["workspace_id"], share["view_id"])["config"]
        except ViewNotFound:
            cfg = {}  # view deleted after sharing → fall back to the full dashboard
    return share["workspace_id"], share["dataset_id"], cfg
