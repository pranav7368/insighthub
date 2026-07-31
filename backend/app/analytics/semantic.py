"""Certified metrics — a small, secure semantic layer.

An admin defines a metric once — an aggregate like SUM(revenue), or a ratio
like SUM(profit)/SUM(revenue) — and it becomes a blessed, reusable definition
the whole app computes consistently. This is the trust play: one place defines
"Revenue", so every surface agrees.

Definitions are **constrained, never free-form SQL**: the aggregate is chosen
from a fixed whitelist and every column is validated against the dataset's real
columns via `safe_identifier`. Each computed value is returned together with
the exact (read-only) SQL that produced it — "show your work" transparency that
turns *trust me* into *verify me*.
"""

import json

from ..core.security import new_id
from ..core.sqlsafe import UnsafeIdentifierError, safe_identifier, safe_table_name
from .engine import get_columns, get_dataset

# aggregate token -> SQL function (fixed whitelist; nothing else can be emitted)
AGGS = {"sum", "avg", "min", "max", "median", "count", "count_distinct"}
KINDS = ("aggregate", "ratio")
FORMATS = ("number", "currency", "percent")
MAX_NAME = 120

_SELECT = "metric_id, dataset_id, name, kind, definition, format, created_at"


class MetricError(ValueError):
    """A metric could not be defined or computed."""


class MetricNotFound(MetricError):
    """No such metric in this workspace."""


def _row(r) -> dict:
    return {
        "metric_id": r[0], "dataset_id": r[1], "name": r[2], "kind": r[3],
        "definition": json.loads(r[4]), "format": r[5], "created_at": str(r[6]),
    }


# --------------------------------------------------- SQL (validated) -------

def _agg_sql(spec, allowed) -> str:
    if not isinstance(spec, dict):
        raise MetricError("invalid metric definition")
    agg = spec.get("agg")
    if agg not in AGGS:
        raise MetricError(f"invalid aggregate {agg!r}")
    if agg == "count":
        return "count(*)"
    col = spec.get("column")
    if not col:
        raise MetricError("a column is required for this aggregate")
    try:
        cq = safe_identifier(col, allowed)  # rejects anything not a real column
    except UnsafeIdentifierError:
        raise MetricError(f"unknown column {col!r}")
    if agg == "count_distinct":
        return f"count(DISTINCT {cq})"
    return f"{agg}({cq})"


def _expr(metric, allowed) -> str:
    d = metric["definition"]
    if metric["kind"] == "aggregate":
        return _agg_sql(d, allowed)
    if metric["kind"] == "ratio":
        if not isinstance(d, dict) or "numerator" not in d or "denominator" not in d:
            raise MetricError("a ratio needs a numerator and a denominator")
        return f"({_agg_sql(d['numerator'], allowed)}) / NULLIF({_agg_sql(d['denominator'], allowed)}, 0)"
    raise MetricError(f"unknown metric kind {metric['kind']!r}")


# ------------------------------------------------------- persistence -------

def _get_metric(con, workspace_id, metric_id) -> dict:
    r = con.execute(f"SELECT {_SELECT} FROM metrics WHERE metric_id = ? AND workspace_id = ?",
                    [metric_id, workspace_id]).fetchone()
    if r is None:
        raise MetricNotFound("metric not found")
    return _row(r)


def create_metric(con, workspace_id, dataset_id, name, kind, definition, fmt=None) -> dict:
    get_dataset(con, workspace_id, dataset_id)  # DatasetNotFound (→404) for other tenants
    name = (name or "").strip()
    if not name:
        raise MetricError("a name is required")
    if kind not in KINDS:
        raise MetricError("invalid metric kind")
    if fmt and fmt not in FORMATS:
        raise MetricError("invalid format")
    allowed = {c.name for c in get_columns(con, workspace_id, dataset_id)}
    _expr({"kind": kind, "definition": definition}, allowed)  # validates columns/aggregates now

    metric_id = new_id("metric")
    con.execute(
        """INSERT INTO metrics (metric_id, workspace_id, dataset_id, name, kind, definition, format)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [metric_id, workspace_id, dataset_id, name[:MAX_NAME], kind, json.dumps(definition), (fmt or None)],
    )
    return _get_metric(con, workspace_id, metric_id)


def delete_metric(con, workspace_id, metric_id) -> int:
    n = con.execute("SELECT count(*) FROM metrics WHERE metric_id = ? AND workspace_id = ?",
                    [metric_id, workspace_id]).fetchone()[0]
    con.execute("DELETE FROM metrics WHERE metric_id = ? AND workspace_id = ?", [metric_id, workspace_id])
    return n


def compute_metric(con, workspace_id, dataset_id, metric) -> tuple[float | None, str]:
    """Return (value, sql). `sql` is a human-readable, read-only query using the
    dataset's friendly name — safe to show, since it is built only from
    whitelisted identifiers and fixed aggregate tokens."""
    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise MetricError("metrics only apply to structured datasets")
    allowed = {c.name for c in get_columns(con, workspace_id, dataset_id)}
    expr = _expr(metric, allowed)
    tq = safe_table_name(dataset["table_name"])
    value = con.execute(f"SELECT {expr} FROM {tq}").fetchone()[0]
    value = None if value is None else float(value)

    display_expr = expr
    if metric.get("format") == "percent":
        display_expr = f"({expr}) * 100"
        if value is not None:
            value = value * 100.0
    sql = f'SELECT {display_expr} AS {json.dumps(metric["name"])[:60]} FROM "{dataset["name"]}"'
    return value, sql


def list_metrics(con, workspace_id, dataset_id, with_values=True) -> list[dict]:
    rows = con.execute(
        f"SELECT {_SELECT} FROM metrics WHERE workspace_id = ? AND dataset_id = ? ORDER BY created_at",
        [workspace_id, dataset_id],
    ).fetchall()
    metrics = [_row(r) for r in rows]
    if with_values:
        for m in metrics:
            try:
                m["value"], m["sql"] = compute_metric(con, workspace_id, dataset_id, m)
                m["error"] = None
            except Exception as exc:  # a bad metric never breaks the whole list
                m["value"], m["sql"], m["error"] = None, None, str(exc)
    return metrics
