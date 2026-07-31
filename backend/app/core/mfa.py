"""Two-factor authentication (TOTP, RFC 6238).

Implemented on the standard library rather than by adding a dependency. TOTP is
not invented cryptography — it is HMAC-SHA1 over a counter plus the dynamic
truncation defined in RFC 4226 — and the RFC publishes test vectors, so the
implementation is checked against the specification itself in
`test_mfa.py::test_matches_rfc6238_vectors` rather than against our own
assumptions. That is a stronger guarantee than trusting an unaudited package,
and it keeps the supply chain small for a security-sensitive path.

Design notes:

* **A one-step window either side.** Phone clocks drift and people type slowly.
  Accepting only the current step rejects legitimate users constantly; a wide
  window weakens the factor. ±1 step (30s) is the usual compromise.
* **Codes are compared in constant time.** A timing oracle on a six-digit code
  is a real attack when an attacker can retry.
* **Replay is refused.** A code stays valid for its whole window, so a code
  observed over the shoulder — or in a screenshot — could be reused within
  30 seconds. The last accepted step is recorded and never accepted twice.
* **Recovery codes are stored hashed**, exactly like passwords. A database
  reader must not be able to bypass the second factor, and single-use is
  enforced by deleting the row on use.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
STEP_SECONDS = 30
WINDOW_STEPS = 1              # accept the neighbouring step on each side
RECOVERY_CODE_COUNT = 10


class MfaError(ValueError):
    """The second factor could not be verified."""


class CodeAlreadyUsed(MfaError):
    """The code was correct but has already been spent inside its window.

    Distinguished from a wrong code so the user is told to wait for the next
    one rather than being sent to reinstall their authenticator app. It leaks
    nothing an attacker can use: they already need the password AND a valid
    code to reach this branch.
    """


# ------------------------------------------------------------- secrets ----

def new_secret() -> str:
    """A base32 secret, the encoding every authenticator app expects."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, email: str, issuer: str = "InsightHub") -> str:
    """The otpauth:// URI an authenticator app scans (or accepts pasted)."""
    label = quote(f"{issuer}:{email}")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


# ---------------------------------------------------------------- TOTP ----

def _decode_secret(secret: str) -> bytes:
    padded = secret.strip().replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except Exception as exc:                      # noqa: BLE001
        raise MfaError("invalid secret") from exc


def code_at(secret: str, counter: int, digits: int = DIGITS,
            digest: str = "sha1") -> str:
    """HOTP (RFC 4226) for an explicit counter — the primitive TOTP builds on."""
    mac = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    truncated = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def current_step(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // STEP_SECONDS)


def generate(secret: str, at: float | None = None) -> str:
    return code_at(secret, current_step(at))


def verify(secret: str, code: str, at: float | None = None,
           last_used_step: int | None = None) -> int:
    """Return the step the code matched, or raise MfaError.

    The caller must persist the returned step so the same code cannot be
    replayed inside its window.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        raise MfaError("enter the 6-digit code from your authenticator app")

    now = current_step(at)
    matched: int | None = None
    for offset in range(-WINDOW_STEPS, WINDOW_STEPS + 1):
        step = now + offset
        if hmac.compare_digest(code_at(secret, step), code):
            matched = step
            break

    if matched is None:
        raise MfaError("that code is not valid — check the time on your device and try again")
    if last_used_step is not None and matched <= last_used_step:
        # Correct code, already spent. Worth its own message: telling someone
        # their valid code is "invalid" sends them to reinstall the app.
        raise CodeAlreadyUsed("that code has already been used — wait for the next one")
    return matched


# ----------------------------------------------------------- recovery -----

def new_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Shown once, at enrolment. The way back in when the phone is lost."""
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
            for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    """SHA-256 rather than bcrypt: these are high-entropy machine-generated
    values, so slow hashing buys nothing, and a login may check ten of them."""
    return hashlib.sha256(code.strip().lower().encode("utf-8")).hexdigest()


def recovery_matches(code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_recovery_code(code), stored_hash)
