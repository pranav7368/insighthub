"""API keys: machine credentials for the data API.

A key is `ihk_<key_id>_<secret>`. Only a SHA-256 of the secret is stored — the
secret is 256 random bits, so a slow password hash would add nothing — and the
full key is shown once, at creation.

What a key may do is deliberately narrower than what its creator may do:

* It acts as the admin who created it, so that person's row rules scope every
  number it reads. If the creator is removed, the key stops working; if the
  creator is demoted, the key is demoted with them.
* Its role is `viewer` or `editor`, never `admin`: a leaked key cannot manage
  the team, billing, privacy settings or other keys.
* It reaches only the data endpoints (`ALLOWED_PREFIXES`). Sign-in, MFA,
  password, team, billing and privacy endpoints refuse keys outright.
* It never sees unmasked PII. The admin exemption from masking is for a person
  looking at their own data in a session, not for a credential that can be
  copied into a script. `rls.secured_relation` enforces this through
  `current_key`, so no read path has to remember to.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

PREFIX = "ihk_"
ROLES = ("viewer", "editor")
MAX_KEYS_PER_WORKSPACE = 50
_RANK = {"viewer": 0, "editor": 1, "admin": 2}
_KEY_RE = re.compile(r"^ihk_([0-9a-f]{16})_([A-Za-z0-9_-]{20,})$")
# last_used_at is a hint, not an audit trail: write it at most this often
_TOUCH_EVERY = timedelta(minutes=1)

# The data endpoints a key may call. Everything else refuses a key.
ALLOWED_PREFIXES = (
    "/api/datasets", "/api/ask", "/api/views", "/api/metrics", "/api/targets",
    "/api/alerts", "/api/reports", "/api/joins", "/api/sources", "/api/shares",
    "/api/templates",
)

# Set for the duration of a request authenticated by a key (see api/deps.py).
current_key: ContextVar[str | None] = ContextVar("ih_api_key", default=None)


class ApiKeyError(Exception):
    """A key could not be created or changed."""


def looks_like_key(token: str) -> bool:
    return token.startswith(PREFIX)


def path_allowed(path: str | None) -> bool:
    return bool(path) and any(path == p or path.startswith(p + "/") for p in ALLOWED_PREFIXES)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now() -> datetime:
    # stored naive-UTC, like every other timestamp in the schema
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _public(row) -> dict:
    key_id, name, role, created_by, email, created_at, last_used_at, expires_at, revoked_at = row
    iso = lambda v: v.isoformat() if v else None   # noqa: E731
    return {
        "key_id": key_id, "name": name, "role": role, "hint": f"{PREFIX}{key_id}_…",
        "created_by": created_by, "created_by_email": email,
        "created_at": iso(created_at), "last_used_at": iso(last_used_at),
        "expires_at": iso(expires_at), "revoked_at": iso(revoked_at),
    }


_SELECT = """SELECT k.key_id, k.name, k.role, k.created_by, u.email, k.created_at,
                    k.last_used_at, k.expires_at, k.revoked_at
             FROM api_keys k LEFT JOIN users u
               ON u.user_id = k.created_by AND u.workspace_id = k.workspace_id"""


def list_keys(con, workspace_id: str) -> list[dict]:
    rows = con.execute(_SELECT + " WHERE k.workspace_id = ? ORDER BY k.created_at DESC",
                       [workspace_id]).fetchall()
    return [_public(r) for r in rows]


def create_key(con, workspace_id: str, created_by: str, *, name: str, role: str = "viewer",
               expires_in_days: int | None = None) -> dict:
    """Create a key. The returned dict carries `key` — the only time it exists
    in plain text anywhere."""
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ApiKeyError("Give the key a name of 1–80 characters, e.g. what will use it.")
    if role not in ROLES:
        raise ApiKeyError("A key's role is viewer or editor.")
    if expires_in_days is not None and not 1 <= int(expires_in_days) <= 730:
        raise ApiKeyError("Expiry must be between 1 and 730 days, or none.")
    live = con.execute("SELECT count(*) FROM api_keys WHERE workspace_id = ? AND revoked_at IS NULL",
                       [workspace_id]).fetchone()[0]
    if live >= MAX_KEYS_PER_WORKSPACE:
        raise ApiKeyError(f"This workspace already has {MAX_KEYS_PER_WORKSPACE} active keys; revoke one first.")

    key_id, secret = secrets.token_hex(8), secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=int(expires_in_days)) if expires_in_days else None
    con.execute(
        """INSERT INTO api_keys (key_id, workspace_id, created_by, name, role, secret_hash, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [key_id, workspace_id, created_by, name, role, _hash(secret), _now(), expires_at],
    )
    row = con.execute(_SELECT + " WHERE k.key_id = ?", [key_id]).fetchone()
    return {**_public(row), "key": f"{PREFIX}{key_id}_{secret}"}


def revoke_key(con, workspace_id: str, key_id: str) -> bool:
    hit = con.execute("SELECT 1 FROM api_keys WHERE workspace_id = ? AND key_id = ? AND revoked_at IS NULL",
                      [workspace_id, key_id]).fetchone()
    if not hit:
        return False
    con.execute("UPDATE api_keys SET revoked_at = ? WHERE workspace_id = ? AND key_id = ?",
                [_now(), workspace_id, key_id])
    return True


def authenticate(con, token: str) -> dict | None:
    """The key's identity, or None for anything not a live, valid key.

    One answer for every failure (unknown, wrong secret, revoked, expired,
    creator gone) so a caller cannot probe which part was wrong.
    """
    m = _KEY_RE.match(token or "")
    if not m:
        return None
    key_id, secret = m.groups()
    row = con.execute(
        """SELECT k.workspace_id, k.created_by, k.role, k.secret_hash, k.expires_at, k.revoked_at,
                  k.last_used_at, u.role
           FROM api_keys k JOIN users u ON u.user_id = k.created_by AND u.workspace_id = k.workspace_id
           WHERE k.key_id = ?""",
        [key_id],
    ).fetchone()
    # compare even when the key is unknown, so timing does not reveal which ids exist
    stored = row[3] if row else _hash("")
    if not hmac.compare_digest(stored, _hash(secret)) or row is None:
        return None
    workspace_id, user_id, key_role, _, expires_at, revoked_at, last_used_at, user_role = row
    now = _now()
    if revoked_at is not None or (expires_at is not None and expires_at <= now):
        return None
    if last_used_at is None or now - last_used_at >= _TOUCH_EVERY:
        con.execute("UPDATE api_keys SET last_used_at = ? WHERE key_id = ?", [now, key_id])
    # never more than the key was granted, never more than its creator has now
    role = min(key_role, user_role, key=lambda r: _RANK.get(r, 0))
    return {"key_id": key_id, "workspace_id": workspace_id, "user_id": user_id, "role": role}
