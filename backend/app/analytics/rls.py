"""Row-level security — which rows of a dataset a given member may see.

The enforcement idea is deliberately small: **every read path asks this module
for the relation to select from, instead of naming the physical table.** With
no rules that is the table itself; with rules it is a filtered subquery:

    "t_ws_abc"                    ->  (SELECT * FROM "t_ws_abc" WHERE "region" IN (?, ?))

A derived table is valid anywhere a table name is (verified against DuckDB for
bare selects, outer WHEREs, GROUP BYs, aliases, nesting and joins), so callers
change one line and thread the extra bound parameters — the filter cannot be
forgotten halfway down a query, and it is impossible to express a rule that
widens access.

Two deliberate choices:

* **Rules bind to a user, not a role.** Roles stay about permissions; data
  scope is per-member, so territories don't require a role each.
* **Fail closed.** If a rule names a column the dataset no longer has (renamed,
  dropped, replaced by an upload), the rule cannot be evaluated — so the read
  returns *nothing* rather than silently falling back to unrestricted. A broken
  rule must never be a quiet grant.

Semantics: rules on the same column OR together (a widening list of values);
rules on different columns AND together (each one narrows further). A member
with no rules on a dataset sees all of it — absence of a rule is not a denial.
"""

import json

from ..core.security import new_id
from ..core.sqlsafe import UnsafeIdentifierError, safe_identifier, safe_table_name
from .engine import get_columns, get_dataset
from .privacy import mask_projection

OPERATORS = ("in", "not_in")
MAX_VALUES = 200

# A predicate that matches no rows. Used when a rule cannot be evaluated.
DENY_ALL = "1 = 0"

_SELECT = "rule_id, workspace_id, dataset_id, user_id, column_name, operator, allowed_values, created_at"


class RuleError(ValueError):
    """A rule could not be created (bad column, operator or values)."""


class RuleNotFound(RuleError):
    """No such rule in this workspace."""


def _row(r) -> dict:
    return {
        "rule_id": r[0], "dataset_id": r[2], "user_id": r[3], "column_name": r[4],
        "operator": r[5], "values": json.loads(r[6]), "created_at": str(r[7]),
    }


# ------------------------------------------------------------ rule CRUD ----

def list_rules(con, workspace_id: str, dataset_id: str | None = None,
               user_id: str | None = None) -> list[dict]:
    sql = f"SELECT {_SELECT} FROM rls_rules WHERE workspace_id = ?"
    params: list = [workspace_id]
    if dataset_id:
        sql += " AND dataset_id = ?"
        params.append(dataset_id)
    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)
    return [_row(r) for r in con.execute(sql + " ORDER BY created_at", params).fetchall()]


def create_rule(con, workspace_id: str, dataset_id: str, user_id: str,
                column_name: str, values, operator: str = "in") -> dict:
    get_dataset(con, workspace_id, dataset_id)   # DatasetNotFound (->404) for other tenants

    if operator not in OPERATORS:
        raise RuleError(f"invalid operator {operator!r}")

    member = con.execute(
        "SELECT count(*) FROM users WHERE user_id = ? AND workspace_id = ?",
        [user_id, workspace_id],
    ).fetchone()[0]
    if not member:
        raise RuleError("no such member in this workspace")

    allowed = {c.name for c in get_columns(con, workspace_id, dataset_id)}
    try:
        safe_identifier(column_name, allowed)     # must be a real column of THIS dataset
    except UnsafeIdentifierError:
        raise RuleError(f"unknown column {column_name!r}")

    if not isinstance(values, (list, tuple)) or not values:
        raise RuleError("at least one value is required")
    if len(values) > MAX_VALUES:
        raise RuleError("too many values")
    values = [str(v) for v in values]

    rule_id = new_id("rls")
    con.execute(
        """INSERT INTO rls_rules
           (rule_id, workspace_id, dataset_id, user_id, column_name, operator, allowed_values)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [rule_id, workspace_id, dataset_id, user_id, column_name, operator, json.dumps(values)],
    )
    row = con.execute(f"SELECT {_SELECT} FROM rls_rules WHERE rule_id = ? AND workspace_id = ?",
                      [rule_id, workspace_id]).fetchone()
    return _row(row)


def delete_rule(con, workspace_id: str, rule_id: str) -> int:
    n = con.execute("SELECT count(*) FROM rls_rules WHERE rule_id = ? AND workspace_id = ?",
                    [rule_id, workspace_id]).fetchone()[0]
    con.execute("DELETE FROM rls_rules WHERE rule_id = ? AND workspace_id = ?",
                [rule_id, workspace_id])
    return n


# ----------------------------------------------------------- enforcement ---

def build_predicate(con, workspace_id: str, user_id: str | None,
                    dataset_id: str) -> tuple[str, list]:
    """The WHERE fragment restricting `user_id` on this dataset.

    Returns ("", []) when unrestricted. Never returns a fragment that widens
    access: the only outcomes are "no filter", "this filter", or DENY_ALL.
    """
    if not user_id:
        return "", []
    rules = list_rules(con, workspace_id, dataset_id, user_id)
    if not rules:
        return "", []

    allowed = {c.name for c in get_columns(con, workspace_id, dataset_id)}

    by_column: dict[str, list[dict]] = {}
    for rule in rules:
        by_column.setdefault(rule["column_name"], []).append(rule)

    clauses: list[str] = []
    params: list = []
    for column, column_rules in by_column.items():
        try:
            cq = safe_identifier(column, allowed)
        except UnsafeIdentifierError:
            # The column vanished (renamed/dropped/replaced by a new upload).
            # We cannot honour the restriction, so we grant nothing.
            return DENY_ALL, []

        alternatives: list[str] = []
        for rule in column_rules:
            marks = ", ".join("?" * len(rule["values"]))
            if rule["operator"] == "not_in":
                # NULL is not excluded by NOT IN, so spell that out
                alternatives.append(f"({cq} NOT IN ({marks}) OR {cq} IS NULL)")
            else:
                alternatives.append(f"{cq} IN ({marks})")
            params.extend(rule["values"])
        # same column -> OR (widen); different columns -> AND (narrow)
        clauses.append(f"({' OR '.join(alternatives)})")

    return " AND ".join(clauses), params


def _is_admin(con, workspace_id: str, user_id: str | None) -> bool:
    """Admins see unmasked values. Looked up here rather than threaded through
    every caller: a read path cannot accidentally omit the role and unmask."""
    if not user_id:
        return True          # system/internal callers (no member context)
    row = con.execute("SELECT role FROM users WHERE user_id = ? AND workspace_id = ?",
                      [user_id, workspace_id]).fetchone()
    return bool(row) and row[0] == "admin"


def secured_relation(con, workspace_id: str, user_id: str | None, dataset: dict) -> tuple[str, list]:
    """The relation every read path should SELECT FROM, plus its bound params.

    Use this in place of `safe_table_name(dataset["table_name"])`; the returned
    params must be prepended to the query's own params, because the subquery
    appears before any outer WHERE in the SQL text.

    It applies BOTH protections, so a caller gets them together or not at all:
    row-level rules become the WHERE, and PII masking becomes a REPLACE over
    the projection.
    """
    table = safe_table_name(dataset["table_name"])
    dataset_id = dataset["dataset_id"]
    where, params = build_predicate(con, workspace_id, user_id, dataset_id)

    projection = ""
    if not _is_admin(con, workspace_id, user_id):
        allowed = {c.name for c in get_columns(con, workspace_id, dataset_id)}
        projection = mask_projection(con, workspace_id, dataset_id, allowed)

    if not where and not projection:
        return table, []
    clause = f" WHERE {where}" if where else ""
    return f"(SELECT *{projection} FROM {table}{clause})", params


def restricts(con, workspace_id: str, user_id: str | None, dataset_id: str) -> bool:
    """Whether this member is row-restricted on this dataset (for UI badges)."""
    where, _ = build_predicate(con, workspace_id, user_id, dataset_id)
    return bool(where)

