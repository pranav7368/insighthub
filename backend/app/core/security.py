"""Password hashing + JWT issuing/verification. The tenancy foundation:
a token encodes the user's workspace_id, and the API resolves the caller's
workspace from the verified token only - never from a query param or header
the client controls - which is what keeps tenants isolated.
"""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from . import config


def _to_bytes(password: str) -> bytes:
    # bcrypt hard-limits the secret to 72 bytes; truncate deterministically
    # so long passwords hash without error (standard bcrypt practice).
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(password), password_hash.encode("ascii"))
    except ValueError:
        return False


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def create_access_token(user_id: str, workspace_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "ws": workspace_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_TTL_MINUTES),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.JWT_ALG)


class TokenError(Exception):
    pass


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALG])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if "sub" not in payload or "ws" not in payload:
        raise TokenError("token missing subject/workspace")
    return payload
