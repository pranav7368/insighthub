"""Password policy.

Deliberately follows NIST SP 800-63B rather than the older "one upper, one
digit, one symbol" ritual: length and a blocklist of known-bad choices stop
real attacks, while composition rules mostly produce `Password1!` and get
written on a sticky note.

So the rules here are:

* **length** — at least `MIN_LENGTH`; long passphrases are the goal, and the
  only upper bound is bcrypt's own 72-byte limit;
* **not obvious** — rejected against a blocklist of the passwords that appear
  at the top of every breach corpus, normalised so `P@ssw0rd` does not sneak
  past `password`;
* **not derived from the account** — an attacker who knows the email address
  knows the first thing to try;
* **not a single repeated or sequential run** — `aaaaaaaaaa`, `1234567890`.

The blocklist is small on purpose. A full breach corpus (HaveIBeenPwned's
k-anonymity range API) is the right answer at scale, and is a network call this
product cannot make on the signup path while claiming to work offline; the
hook to add it later is `_is_breached`.
"""

import re

MIN_LENGTH = 10
MAX_LENGTH = 72          # bcrypt truncates beyond this; refuse rather than silently cut


class WeakPassword(ValueError):
    """The password is not acceptable. The message is safe to show a user."""


# The head of every leaked-password ranking, plus the ones this product invites
# by name. Stored normalised (see _normalise).
_COMMON = {
    "password", "passw0rd", "password1", "password123", "123456", "12345678",
    "123456789", "1234567890", "qwerty", "qwertyuiop", "abc123", "letmein",
    "welcome", "welcome1", "admin", "administrator", "root", "toor",
    "iloveyou", "monkey", "dragon", "sunshine", "princess", "football",
    "baseball", "master", "shadow", "superman", "trustno1", "changeme",
    "secret", "starwars", "whatever", "zaq12wsx", "asdfghjkl",
    # this product's own words are the first thing anyone tries
    "insighthub", "insighthub1", "insight123", "analytics", "dashboard",
}

# leetspeak -> letter, so P@ssw0rd normalises onto password
_LEET = str.maketrans({"@": "a", "4": "a", "3": "e", "1": "l", "0": "o",
                       "$": "s", "5": "s", "7": "t", "!": "i"})


def _normalise(password: str) -> str:
    return password.lower().translate(_LEET)


def _is_breached(password: str) -> bool:
    """Hook for a real breach-corpus check (HIBP range API).

    Intentionally offline for now: the signup path must work with no network.
    When this is wired up, call it from `validate` and keep the failure mode
    fail-open — a breach service being down must not stop signups.
    """
    return False


def _is_sequential_or_repeated(password: str) -> bool:
    stripped = password.strip()
    if len(set(stripped)) <= 2:                       # aaaaaaaaaa, ababababab
        return True
    lowered = stripped.lower()
    runs = ("abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiopasdfghjklzxcvbnm")
    for run in runs:
        if lowered in run or lowered in run[::-1]:
            return True
    return False


def _account_tokens(*identifiers: str) -> set[str]:
    tokens = set()
    for value in identifiers:
        if not value:
            continue
        for part in re.split(r"[^a-z0-9]+", value.lower()):
            if len(part) >= 4:
                tokens.add(part)
    return tokens


def validate(password: str, email: str = "", workspace_name: str = "") -> None:
    """Raise WeakPassword if the password is not acceptable. Returns None."""
    if password is None or len(password) < MIN_LENGTH:
        raise WeakPassword(f"password must be at least {MIN_LENGTH} characters")
    if len(password.encode("utf-8")) > MAX_LENGTH:
        raise WeakPassword(f"password must be at most {MAX_LENGTH} bytes")

    # Check the literal password AND its de-leeted form. Normalising alone is
    # not enough: the leet map rewrites digits, so a pure-digit classic like
    # "1234567890" becomes "l2ea56t89o" and stops matching its own entry.
    lowered = password.lower()
    normalised = _normalise(password)
    forms = {lowered, normalised}

    if forms & _COMMON:
        raise WeakPassword("that password is one of the most common in use — pick another")
    # also catch "password" padded to length, e.g. password0000
    for common in _COMMON:
        if len(common) < 6:
            continue
        if any(f.startswith(common) and len(f) - len(common) <= 4 for f in forms):
            raise WeakPassword("that password is too close to a very common one — pick another")

    if _is_sequential_or_repeated(password):
        raise WeakPassword("password must not be a single repeated or sequential run of characters")

    for token in _account_tokens(email, workspace_name):
        if token in normalised:
            raise WeakPassword("password must not contain your email address or workspace name")

    if _is_breached(password):
        raise WeakPassword("that password has appeared in a known data breach — pick another")
