"""Request dependencies. The critical one, get_principal, resolves the
caller's workspace from the VERIFIED JWT only - never from a query param,
body, or header the client can forge. This is the mechanism that enforces
tenant isolation: downstream code receives a workspace_id it can trust.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from ..core.security import TokenError, decode_access_token


@dataclass
class Principal:
    user_id: str
    workspace_id: str
    role: str


def get_principal(authorization: str = Header(default="")) -> Principal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :].strip()
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}")
    return Principal(user_id=payload["sub"], workspace_id=payload["ws"], role=payload.get("role", "viewer"))


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
