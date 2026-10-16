"""Request dependencies. The critical one, get_principal, resolves the
caller's workspace from the VERIFIED JWT only - never from a query param,
body, or header the client can forge. This is the mechanism that enforces
tenant isolation: downstream code receives a workspace_id it can trust.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..core import apikeys
from ..core.security import TokenError, decode_access_token


@dataclass
class Principal:
    user_id: str
    workspace_id: str
    role: str
    # False when the workspace requires a second factor this member has not
    # enrolled. They are authenticated, but may only reach MFA setup.
    mfa_satisfied: bool = True
    # set when the caller is an API key rather than a signed-in person
    key_id: str | None = None


def _resolve_key(token: str, path: str | None, allow_keys: bool) -> Principal:
    if not allow_keys or not apikeys.path_allowed(path):
        raise HTTPException(status_code=403, detail="API keys can only call the data API — "
                                                    "sign in to manage accounts, team, billing or privacy")
    from ..core import db

    found = apikeys.authenticate(db.connect(), token)
    if found is None:
        raise HTTPException(status_code=401, detail="invalid, expired or revoked API key")
    return Principal(user_id=found["user_id"], workspace_id=found["workspace_id"], role=found["role"],
                     key_id=found["key_id"])


def _resolve(authorization: str, path: str | None = None, allow_keys: bool = False) -> Principal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :].strip()
    if apikeys.looks_like_key(token):
        return _resolve_key(token, path, allow_keys)
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}")

    # The token proves identity; the database decides whether that identity is
    # still valid and what it may do *now*. Without this a JWT cannot be taken
    # back — a removed member keeps access until it expires — and a role change
    # would not apply until the user happened to log in again.
    from ..core import db

    con = db.connect()
    row = con.execute(
        """SELECT u.role, u.token_epoch, COALESCE(u.mfa_enabled, false),
                  COALESCE(w.require_mfa, false)
           FROM users u JOIN workspaces w ON w.workspace_id = u.workspace_id
           WHERE u.user_id = ? AND u.workspace_id = ?""",
        [payload["sub"], payload["ws"]],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="account no longer exists")
    role, epoch, has_mfa, workspace_requires_mfa = row[0], int(row[1] or 0), bool(row[2]), bool(row[3])
    if int(payload.get("ep", 0)) != epoch:
        raise HTTPException(status_code=401, detail="session has been revoked — sign in again")

    return Principal(
        user_id=payload["sub"], workspace_id=payload["ws"], role=role,
        mfa_satisfied=(has_mfa or not workspace_requires_mfa),
    )


async def get_principal(request: Request, authorization: str = Header(default="")) -> Principal:
    """The dependency for every endpoint that is not MFA enrolment.

    Enforcing the workspace's MFA requirement HERE rather than per-endpoint is
    deliberate: a new endpoint is covered by default instead of by someone
    remembering to add a check, which is the same reason row-level security has
    a single choke point.

    It is async only so that `apikeys.current_key` is set in the request's own
    context, which the (threadpool) endpoint then inherits; the lookup itself
    still runs off the event loop.
    """
    principal = await run_in_threadpool(_resolve, authorization, request.url.path, True)
    apikeys.current_key.set(principal.key_id)
    if not principal.mfa_satisfied:
        raise HTTPException(
            status_code=403,
            detail="mfa_setup_required: this workspace requires two-factor "
                   "authentication — set it up to continue",
        )
    return principal


def get_principal_for_mfa_setup(authorization: str = Header(default="")) -> Principal:
    """Enrolment endpoints only.

    Without this exemption the requirement would be a lockout: you cannot
    enrol a second factor if every endpoint demands one first.
    """
    return _resolve(authorization)


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return principal


def require_editor(principal: Principal = Depends(get_principal)) -> Principal:
    """Content mutations (upload, dashboards, metrics, alerts, shares…) — an
    admin or an editor. Viewers are read-only. User management stays
    admin-only (require_admin)."""
    if principal.role not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="editor or admin role required")
    return principal
