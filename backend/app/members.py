"""Team management — members and roles within a workspace.

Roles: admin (full control incl. user management), editor (all content
mutations), viewer (read-only). Everything here is workspace-scoped; the
API layer gates these to admins. Guards keep a workspace from ever losing its
last admin (which would lock everyone out of user management), and nobody can
delete themselves.
"""

import secrets

from .core import passwords
from .core.security import hash_password, new_id, verify_password

ROLES = ("admin", "editor", "viewer")
MIN_PASSWORD = 8


class MemberError(ValueError):
    """A member operation was rejected (bad role, duplicate, last-admin, …)."""


class MemberNotFound(MemberError):
    """No such member in this workspace."""


def list_members(con, workspace_id: str) -> list[dict]:
    rows = con.execute(
        "SELECT user_id, email, role, created_at FROM users WHERE workspace_id = ? ORDER BY created_at",
        [workspace_id],
    ).fetchall()
    return [{"user_id": r[0], "email": r[1], "role": r[2], "created_at": str(r[3])} for r in rows]


def _admin_count(con, workspace_id: str, exclude: str | None = None) -> int:
    if exclude:
        return con.execute(
            "SELECT count(*) FROM users WHERE workspace_id = ? AND role = 'admin' AND user_id != ?",
            [workspace_id, exclude],
        ).fetchone()[0]
    return con.execute(
        "SELECT count(*) FROM users WHERE workspace_id = ? AND role = 'admin'", [workspace_id]
    ).fetchone()[0]


def create_member(con, workspace_id: str, email: str, role: str, password: str | None = None) -> dict:
    """Add a teammate. If no password is given, a temporary one is generated and
    returned once so the admin can hand it off (the member can change it later)."""
    email = (email or "").strip()
    if not email:
        raise MemberError("an email is required")
    if role not in ROLES:
        raise MemberError("invalid role")
    if con.execute("SELECT 1 FROM users WHERE email = ?", [email]).fetchone():
        raise MemberError("that email is already registered")

    temp = None
    if password:
        try:
            passwords.validate(password, email=email)
        except passwords.WeakPassword as exc:
            raise MemberError(str(exc))
    else:
        # generated, so it is long and random by construction — the policy
        # exists to stop humans choosing badly, not to second-guess urandom
        password = secrets.token_urlsafe(12)
        temp = password

    user_id = new_id("usr")
    con.execute(
        "INSERT INTO users (user_id, workspace_id, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
        [user_id, workspace_id, email, hash_password(password), role],
    )
    return {"user_id": user_id, "email": email, "role": role, "temp_password": temp}


def update_member_role(con, workspace_id: str, actor_user_id: str, user_id: str, role: str) -> dict:
    if role not in ROLES:
        raise MemberError("invalid role")
    target = con.execute(
        "SELECT role FROM users WHERE user_id = ? AND workspace_id = ?", [user_id, workspace_id]
    ).fetchone()
    if target is None:
        raise MemberNotFound("member not found")
    if target[0] == "admin" and role != "admin" and _admin_count(con, workspace_id, exclude=user_id) == 0:
        raise MemberError("this is the workspace's only admin — promote someone else first")
    # bump the epoch so a demotion cannot be outlived by an already-issued token
    con.execute("UPDATE users SET role = ?, token_epoch = COALESCE(token_epoch, 0) + 1 "
                "WHERE user_id = ? AND workspace_id = ?",
                [role, user_id, workspace_id])
    return {"user_id": user_id, "role": role}


def delete_member(con, workspace_id: str, actor_user_id: str, user_id: str) -> dict:
    if user_id == actor_user_id:
        raise MemberError("you cannot remove yourself")
    target = con.execute(
        "SELECT role FROM users WHERE user_id = ? AND workspace_id = ?", [user_id, workspace_id]
    ).fetchone()
    if target is None:
        raise MemberNotFound("member not found")
    if target[0] == "admin" and _admin_count(con, workspace_id, exclude=user_id) == 0:
        raise MemberError("cannot remove the workspace's only admin")
    con.execute("DELETE FROM users WHERE user_id = ? AND workspace_id = ?", [user_id, workspace_id])
    return {"ok": True}


def change_password(con, user_id: str, old_password: str, new_password: str) -> dict:
    row = con.execute("SELECT password_hash FROM users WHERE user_id = ?", [user_id]).fetchone()
    if row is None:
        raise MemberNotFound("user not found")
    if not verify_password(old_password, row[0]):
        raise MemberError("current password is incorrect")
    email = con.execute("SELECT email FROM users WHERE user_id = ?", [user_id]).fetchone()[0]
    try:
        passwords.validate(new_password, email=email)
    except passwords.WeakPassword as exc:
        raise MemberError(str(exc))
    # Changing a password must end every session opened with the old one —
    # otherwise "I think someone has my password" has no remedy.
    con.execute(
        """UPDATE users
           SET password_hash = ?, token_epoch = COALESCE(token_epoch, 0) + 1,
               failed_logins = 0, locked_until = NULL
           WHERE user_id = ?""",
        [hash_password(new_password), user_id],
    )
    return {"ok": True, "sessions_revoked": True}
