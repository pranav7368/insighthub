"""The SQL-injection defense: identifier validation, sanitization, whitelist."""

import pytest

from app.core.sqlsafe import (
    UnsafeIdentifierError,
    is_valid_identifier,
    quote_identifier,
    safe_identifier,
    sanitize_identifier,
)


def test_valid_identifier_accepts_normal_names():
    assert is_valid_identifier("revenue")
    assert is_valid_identifier("units_sold")
    assert is_valid_identifier("_private")


@pytest.mark.parametrize("bad", [
    "revenue; DROP TABLE users",
    'a" OR "1"="1',
    "col name with spaces",
    "1starts_with_digit",
    "col--comment",
    "col/*x*/",
    "",
])
def test_valid_identifier_rejects_injection_shapes(bad):
    assert not is_valid_identifier(bad)


def test_sanitize_makes_arbitrary_headers_safe():
    assert sanitize_identifier("Revenue (USD)") == "Revenue_USD"
    assert sanitize_identifier("2024 Q1") == "c_2024_Q1"          # leading digit prefixed
    assert sanitize_identifier('"; DROP TABLE users; --') == "DROP_TABLE_users"
    assert is_valid_identifier(sanitize_identifier('evil"; DELETE'))


def test_quote_identifier_escapes_and_rejects_invalid():
    assert quote_identifier("revenue") == '"revenue"'
    with pytest.raises(UnsafeIdentifierError):
        quote_identifier('a"; DROP')


def test_safe_identifier_enforces_whitelist():
    allowed = {"revenue", "branch"}
    assert safe_identifier("revenue", allowed) == '"revenue"'
    # a syntactically-valid name that is NOT a real column is still rejected
    with pytest.raises(UnsafeIdentifierError):
        safe_identifier("password_hash", allowed)
    # an injection payload is rejected before the whitelist even matters
    with pytest.raises(UnsafeIdentifierError):
        safe_identifier("revenue; DROP TABLE users", allowed)
