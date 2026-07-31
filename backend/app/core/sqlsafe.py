"""SQL identifier safety - the fix for the injection surface that existed
when column/table names (some derived from user-uploaded files) were spliced
into SQL with f-strings.

Two layers of defense, both required:

  1. INGEST-TIME sanitization: a column name coming off an uploaded file is
     stripped to [A-Za-z0-9_] before it is ever used as a real identifier,
     and that sanitized name is what gets stored in metadata (see ingest).

  2. QUERY-TIME whitelisting: before any identifier is placed into SQL, the
     caller passes the set of identifiers that legitimately exist for that
     dataset (read from metadata). `safe_identifier` rejects anything not in
     that allowlist. Even a name that somehow slipped past sanitization
     cannot reach the query unless it matches a known column.

On top of both, `quote_identifier` double-quotes and escapes, so an
identifier is never bare in the SQL string. Values always go through bound
parameters (?), never string interpolation.
"""

import re

# A validated identifier: starts with a letter/underscore, then letters,
# digits, underscores. No spaces, quotes, semicolons, comments, etc.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UnsafeIdentifierError(ValueError):
    """Raised when an identifier fails validation or is not in the allowlist."""


def sanitize_identifier(name: str) -> str:
    """Ingest-time: coerce an arbitrary column/label into a legal identifier.

    Non-alphanumerics collapse to underscores; a leading digit gets an 'c_'
    prefix; empty result becomes 'col'. Deterministic so re-ingesting the
    same file yields the same identifiers.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(name).strip()).strip("_")
    if not cleaned:
        return "col"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned


def is_valid_identifier(name: str) -> bool:
    return bool(_IDENTIFIER_RE.match(name))


def quote_identifier(name: str) -> str:
    """Double-quote an already-validated identifier for use in SQL.

    Must only be called on names that passed `safe_identifier`. Embedded
    double-quotes are escaped defensively even though validation forbids them.
    """
    if not is_valid_identifier(name):
        raise UnsafeIdentifierError(f"refusing to quote invalid identifier {name!r}")
    return '"' + name.replace('"', '""') + '"'


def safe_identifier(name: str, allowed: set[str] | frozenset[str]) -> str:
    """Query-time gate: validate `name`, confirm it is in `allowed`, return
    it quoted and ready to splice into SQL. Raises otherwise."""
    if not is_valid_identifier(name):
        raise UnsafeIdentifierError(f"invalid SQL identifier {name!r}")
    if name not in allowed:
        raise UnsafeIdentifierError(f"identifier {name!r} is not a known column of this dataset")
    return quote_identifier(name)


def safe_table_name(name: str) -> str:
    """Table names are system-generated (never user input), but still
    validated + quoted so nothing bare reaches SQL."""
    if not is_valid_identifier(name):
        raise UnsafeIdentifierError(f"invalid table name {name!r}")
    return quote_identifier(name)
