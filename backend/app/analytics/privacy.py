"""PII detection and masking.

Sensitive columns are detected at ingest (by name *and* by what the values
actually look like) and recorded as a policy an admin can override. On the way
out, a masked column is redacted for everyone except admins:

    priya.sharma@acme.com  ->  pr***@acme.com
    9876543210             ->  ******3210

Two properties make this cheap to trust:

* **Redaction happens in the projection, not in Python.** The mask is applied
  by the same relation rewrite that enforces row-level security
  (`rls.secured_relation`), using DuckDB's `SELECT * REPLACE (...)`. So every
  read path already routed through that helper is masked too — dashboards,
  breakdowns, filter dropdowns, Ask, CSV export — with no per-endpoint step to
  forget, and the source data is never altered.
* **The policy is reversible.** Nothing is overwritten on ingest, so widening
  access later is a settings change, not a re-upload.

A detected PII column is never left as a *measure*: identifiers are not
metrics (summing a phone number is meaningless), and demoting them keeps the
masked expression — which is text — out of any aggregate.
"""

import re

from ..core.sqlsafe import UnsafeIdentifierError, safe_identifier

EMAIL = "email"
PHONE = "phone"
NATIONAL_ID = "national_id"
PERSON_NAME = "person_name"
KINDS = (EMAIL, PHONE, NATIONAL_ID, PERSON_NAME)

# Name hints. Matched on word boundaries against the sanitized column name, so
# "product_name" does not read as a person's name.
_NAME_HINTS = {
    EMAIL: {"email", "e_mail", "mail", "email_address"},
    PHONE: {"phone", "mobile", "telephone", "tel", "msisdn", "contact_number", "phone_number"},
    NATIONAL_ID: {"aadhaar", "aadhar", "pan", "pan_number", "ssn", "national_id", "passport",
                  "tax_id", "nin"},
    PERSON_NAME: {"customer_name", "client_name", "employee_name", "contact_name", "full_name",
                  "first_name", "last_name", "patient_name", "person_name"},
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_PHONE_SHAPE = re.compile(r"^\+?[\d\s\-()]+$")
_AADHAAR_RE = re.compile(r"^\d{12}$")
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$", re.I)
# Dates are the classic false positive: "2025-01-05" is ten digits with
# separators, which any loose phone pattern happily accepts.
_DATEISH_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")


def _looks_like_phone(value: str) -> bool:
    if _DATEISH_RE.match(value) or not _PHONE_SHAPE.match(value):
        return False
    return 10 <= sum(c.isdigit() for c in value) <= 13

# how much of a column's non-null sample must match before the values alone
# are enough to call it PII
_VALUE_CONFIDENCE = 0.8
_SAMPLE = 200


def _tokens(column_name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", column_name.lower()) if t}


def _by_name(column_name: str) -> str | None:
    name = column_name.lower().strip()
    tokens = _tokens(name)
    for kind, hints in _NAME_HINTS.items():
        for hint in hints:
            # match the whole name, or the hint's words appearing as tokens
            if name == hint or set(hint.split("_")) <= tokens:
                return kind
    return None


def _by_values(values) -> str | None:
    sample = [str(v).strip() for v in values if v is not None and str(v).strip()][:_SAMPLE]
    if len(sample) < 5:
        return None

    def frac(test) -> float:
        return sum(1 for v in sample if test(v)) / len(sample)

    if frac(_EMAIL_RE.match) >= _VALUE_CONFIDENCE:
        return EMAIL
    if frac(_AADHAAR_RE.match) >= _VALUE_CONFIDENCE or frac(_PAN_RE.match) >= _VALUE_CONFIDENCE:
        return NATIONAL_ID
    if frac(_looks_like_phone) >= _VALUE_CONFIDENCE:
        return PHONE
    return None


def detect_pii(column_name: str, values=()) -> str | None:
    """The kind of PII a column holds, or None.

    The name is checked first (an empty or unrepresentative sample should not
    stop `customer_email` being treated as email), then the values — which
    catches a sensitive column whose name gives nothing away.
    """
    return _by_name(column_name) or _by_values(values)


# ------------------------------------------------------------- policies ---

def set_policy(con, workspace_id: str, dataset_id: str, column_name: str,
               pii_kind: str | None, masked: bool) -> None:
    con.execute(
        "DELETE FROM column_policies WHERE dataset_id = ? AND workspace_id = ? AND column_name = ?",
        [dataset_id, workspace_id, column_name],
    )
    con.execute(
        """INSERT INTO column_policies (dataset_id, workspace_id, column_name, pii_kind, masked)
           VALUES (?, ?, ?, ?, ?)""",
        [dataset_id, workspace_id, column_name, pii_kind, bool(masked)],
    )


def list_policies(con, workspace_id: str, dataset_id: str) -> list[dict]:
    rows = con.execute(
        """SELECT column_name, pii_kind, masked FROM column_policies
           WHERE dataset_id = ? AND workspace_id = ? ORDER BY column_name""",
        [dataset_id, workspace_id],
    ).fetchall()
    return [{"column_name": r[0], "pii_kind": r[1], "masked": bool(r[2])} for r in rows]


def masked_columns(con, workspace_id: str, dataset_id: str) -> dict[str, str]:
    """{column -> pii_kind} for columns currently set to mask."""
    return {
        r[0]: (r[1] or PERSON_NAME)
        for r in con.execute(
            """SELECT column_name, pii_kind FROM column_policies
               WHERE dataset_id = ? AND workspace_id = ? AND masked""",
            [dataset_id, workspace_id],
        ).fetchall()
    }


# --------------------------------------------------------------- masking ---

def mask_expression(quoted_column: str, kind: str) -> str:
    """A SQL expression redacting `quoted_column`, preserving enough shape for
    the value to stay recognisable (and groupable) without being identifying."""
    text = f"CAST({quoted_column} AS VARCHAR)"
    if kind == EMAIL:
        redacted = (f"substr({text}, 1, 2) || '***@' || "
                    f"CASE WHEN position('@' IN {text}) > 0 "
                    f"THEN split_part({text}, '@', 2) ELSE 'hidden' END")
    elif kind == PHONE:
        redacted = f"'******' || right({text}, 4)"
    elif kind == NATIONAL_ID:
        redacted = f"'********' || right({text}, 4)"
    else:  # person_name and anything else
        redacted = f"substr({text}, 1, 1) || '*****'"
    return f"CASE WHEN {quoted_column} IS NULL THEN NULL ELSE {redacted} END"


def mask_projection(con, workspace_id: str, dataset_id: str, allowed: set[str]) -> str:
    """The `REPLACE (...)` clause redacting this dataset's masked columns, or ""
    when nothing is masked. Column names are whitelist-validated like any other
    identifier; a policy naming a column that no longer exists is skipped
    (there is nothing left to leak)."""
    parts = []
    for column, kind in masked_columns(con, workspace_id, dataset_id).items():
        try:
            cq = safe_identifier(column, allowed)
        except UnsafeIdentifierError:
            continue
        parts.append(f"{mask_expression(cq, kind)} AS {cq}")
    return f" REPLACE ({', '.join(parts)})" if parts else ""
