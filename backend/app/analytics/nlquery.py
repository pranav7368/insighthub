"""Grounded conversational analytics: natural-language question -> a
validated structured QueryIntent -> safe SQL -> real numbers + a chart.

The LLM's ONLY job is understanding the question and emitting a QueryIntent
(which measure, which aggregation, group by what, filtered how). It never
writes SQL and never produces a number. This module then:
  * validates every field of the intent against the dataset's real schema
    (unknown columns / aggregations are rejected),
  * builds the SQL itself through the same `safe_identifier` whitelist that
    protects the rest of the engine (so it is injection-proof), and
  * executes it, so the numbers are computed deterministically.

The natural-language answer sentence is templated from the actual result
rows in code - not written by the LLM - so a conversational answer carries
the same "no invented numbers" guarantee as everything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from string import Template

from ..core import config
from ..core.sqlsafe import quote_identifier, safe_identifier, safe_table_name
from ..qa.llm import LLM, extract_json, get_llm
from .engine import DatasetNotFound, get_columns, get_dataset
from .intelligence import format_value

AGGREGATIONS = {"sum", "avg", "min", "max", "count"}
CHART_TYPES = {"bar", "line", "pie", "kpi", "table"}
MONTH = "__month__"


class QueryError(Exception):
    pass


@dataclass
class QueryIntent:
    metric: str | None = None
    aggregation: str = "sum"
    group_by: str | None = None
    filters: dict = field(default_factory=dict)
    sort: str | None = "desc"
    limit: int | None = None
    chart_type: str = "bar"

    def as_dict(self):
        return self.__dict__.copy()


# ---------------------------------------------------------- schema -------

def build_schema(con, workspace_id: str, dataset_id: str, user_id: str | None = None) -> dict:
    from .rls import secured_relation

    dataset = get_dataset(con, workspace_id, dataset_id)
    if dataset["kind"] != "structured":
        raise DatasetNotFound(f"{dataset_id} is not a structured dataset")
    columns = get_columns(con, workspace_id, dataset_id)
    table, rls_params = secured_relation(con, workspace_id, user_id, dataset)
    measures = [{"name": c.name, "subtype": c.subtype} for c in columns if c.role == "measure"]
    dimensions = []
    for c in columns:
        if c.role == "dimension":
            vals = con.execute(
                f"SELECT DISTINCT {safe_identifier(c.name, {c.name})} FROM {table} "
                f"WHERE {safe_identifier(c.name, {c.name})} IS NOT NULL LIMIT 50",
                list(rls_params),
            ).fetchall()
            dimensions.append({"name": c.name, "values": [v[0] for v in vals]})
    date_cols = [c.name for c in columns if c.role == "date"]
    return {
        "dataset_id": dataset_id, "dataset_name": dataset["name"], "table": dataset["table_name"],
        "measures": measures, "dimensions": dimensions,
        "date_column": date_cols[0] if date_cols else None,
        "allowed": {c.name for c in columns},
    }


# ---------------------------------------------- question -> intent -------

def question_to_intent(question: str, schema: dict, llm: LLM | None = None) -> QueryIntent:
    llm = llm or get_llm()
    prompt_schema = {
        "measures": schema["measures"],
        "dimensions": [{"name": d["name"], "example_values": d["values"][:8]} for d in schema["dimensions"]],
        "date_column": schema["date_column"],
    }
    payload = {"question": question, "schema": prompt_schema}
    prompt = Template(config.prompt("nl_to_query")).substitute(payload_json=json.dumps(payload, indent=1))
    parsed = extract_json(llm.complete(prompt, max_tokens=512))
    return _validate_intent(parsed, schema)


def _validate_intent(parsed: dict, schema: dict) -> QueryIntent:
    """Coerce and whitelist an intent against the real schema - the safety
    gate between the LLM's suggestion and any SQL."""
    allowed_measures = {m["name"] for m in schema["measures"]}
    allowed_dims = {d["name"] for d in schema["dimensions"]}

    # A reference the dataset has no idea about (a region that does not exist,
    # a column we never received). Answering anyway means computing a real
    # number about something the user did not ask for.
    unresolved = [str(u) for u in (parsed.get("unresolved") or []) if str(u).strip()]
    if unresolved:
        raise QueryError(
            f"this dataset has nothing matching {unresolved[0]!r}, so that question "
            "cannot be answered from it"
        )

    agg = str(parsed.get("aggregation", "sum")).lower()
    if agg not in AGGREGATIONS:
        agg = "sum"

    # A named metric we do not have is NOT a validation detail to paper over.
    # Substituting the first available measure answers a different question
    # than the one asked, with a real number and real SQL behind it — the
    # "plausible but wrong" failure this product exists to prevent. Refuse.
    metric = parsed.get("metric")
    named = metric is not None and str(metric).strip() != ""
    if named and metric not in allowed_measures:
        available = ", ".join(sorted(allowed_measures)) or "none"
        raise QueryError(
            f"this dataset has nothing called {str(metric)!r} to measure. "
            f"Available measures: {available}."
        )
    if metric not in allowed_measures:
        metric = next(iter(allowed_measures), None) if agg != "count" else None

    group_by = parsed.get("group_by")
    if group_by == MONTH:
        group_by = MONTH if schema["date_column"] else None
    elif group_by not in allowed_dims:
        group_by = None

    filters = {}
    for k, v in (parsed.get("filters") or {}).items():
        if k in allowed_dims:
            filters[k] = v

    sort = parsed.get("sort")
    sort = sort if sort in ("asc", "desc") else "desc"

    limit = parsed.get("limit")
    try:
        limit = int(limit) if limit is not None else None
        if limit is not None:
            limit = max(1, min(limit, 100))
    except (TypeError, ValueError):
        limit = None

    chart = str(parsed.get("chart_type", "")).lower()
    if chart not in CHART_TYPES:
        chart = "line" if group_by == MONTH else "bar" if group_by else "kpi"

    return QueryIntent(metric=metric, aggregation=agg, group_by=group_by,
                       filters=filters, sort=sort, limit=limit, chart_type=chart)


# ---------------------------------------------- intent -> results --------

def _display_sql(sql: str, table_quoted: str, dataset_name: str, params: list) -> str:
    """A human-readable, read-only rendering of the executed query: the internal
    table name is swapped for the dataset's friendly name and the bound `?`
    parameters are inlined (display only — the real query stays parameterized)."""
    disp = sql.replace(table_quoted, f'"{dataset_name}"')
    for p in params:
        lit = "NULL" if p is None else (f"'{p}'" if isinstance(p, str) else str(p))
        disp = disp.replace("?", lit, 1)
    return disp


def execute_intent(con, workspace_id: str, dataset_id: str, intent: QueryIntent,
                   user_id: str | None = None) -> dict:
    from .rls import secured_relation

    schema = build_schema(con, workspace_id, dataset_id, user_id)
    allowed = schema["allowed"]
    # display only: swapped for the friendly dataset name in the shown SQL, so
    # the row filter stays visible. Never used as a FROM.  rls-raw-table-ok
    physical = safe_table_name(schema["table"])
    table, rls_params = secured_relation(
        con, workspace_id, user_id, {"table_name": schema["table"], "dataset_id": dataset_id})
    dataset_name = schema["dataset_name"]
    date_col = schema["date_column"]
    subtype = next((m["subtype"] for m in schema["measures"] if m["name"] == intent.metric), None)

    # value expression
    if intent.aggregation == "count":
        value_expr = "COUNT(*)"
    else:
        if intent.metric not in allowed:
            raise QueryError("no valid measure to aggregate")
        value_expr = f"{intent.aggregation.upper()}({safe_identifier(intent.metric, allowed)})"

    # filters (values are always bound parameters)
    where, params = [], list(rls_params)   # RLS binds first (subquery precedes WHERE)
    for col, val in intent.filters.items():
        where.append(f"{safe_identifier(col, allowed)} = ?")
        params.append(val)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    readable = _describe(intent, schema)

    if intent.group_by == MONTH and date_col:
        dcol = safe_identifier(date_col, allowed)
        extra = f"TRY_CAST({dcol} AS TIMESTAMP) IS NOT NULL"
        w = f"{where_sql} AND {extra}" if where_sql else f"WHERE {extra}"
        sql = (f"SELECT strftime(date_trunc('month', TRY_CAST({dcol} AS TIMESTAMP)),'%Y-%m') AS k, "
               f"{value_expr} AS v FROM {table} {w} GROUP BY 1 ORDER BY 1")
        rows = con.execute(sql, params).fetchall()
        data = [{"label": r[0], "value": r[1]} for r in rows]
        return {"kind": "series", "x": "month", "data": data, "subtype": subtype,
                "chart_type": intent.chart_type, "query": readable, "intent": intent.as_dict(),
                "sql": _display_sql(sql, physical, dataset_name, params)}

    if intent.group_by and intent.group_by in allowed:
        gcol = safe_identifier(intent.group_by, allowed)
        order = "ASC" if intent.sort == "asc" else "DESC"
        limit = intent.limit or 20
        w = f"{where_sql} AND {gcol} IS NOT NULL" if where_sql else f"WHERE {gcol} IS NOT NULL"
        sql = (f"SELECT {gcol} AS k, {value_expr} AS v FROM {table} {w} "
               f"GROUP BY 1 ORDER BY v {order} NULLS LAST LIMIT {limit}")
        rows = con.execute(sql, params).fetchall()
        data = [{"label": r[0], "value": r[1]} for r in rows]
        return {"kind": "grouped", "x": intent.group_by, "data": data, "subtype": subtype,
                "chart_type": intent.chart_type, "query": readable, "intent": intent.as_dict(),
                "sql": _display_sql(sql, physical, dataset_name, params)}

    # scalar (KPI)
    sql = f"SELECT {value_expr} AS v FROM {table} {where_sql}"
    value = con.execute(sql, params).fetchone()[0]
    if value is None and intent.filters:
        # No rows matched. Reporting "0" here would present the absence of data
        # as a measured fact — e.g. "revenue for a region that does not exist
        # is zero". Say what actually happened instead.
        described = ", ".join(f"{k} = {v}" for k, v in intent.filters.items())
        raise QueryError(f"no rows match {described}, so there is nothing to measure")
    return {"kind": "scalar", "value": value, "subtype": subtype,
            "chart_type": "kpi", "query": readable, "intent": intent.as_dict(),
            "sql": _display_sql(sql, physical, dataset_name, params)}


def _describe(intent: QueryIntent, schema: dict) -> str:
    metric = intent.metric or "rows"
    agg = "count of" if intent.aggregation == "count" else f"{intent.aggregation} of"
    parts = [f"{agg} {metric.replace('_', ' ')}"]
    if intent.group_by == MONTH:
        parts.append("by month")
    elif intent.group_by:
        parts.append(f"by {intent.group_by.replace('_', ' ')}")
    if intent.filters:
        parts.append("where " + ", ".join(f"{k.replace('_',' ')} = {v}" for k, v in intent.filters.items()))
    if intent.limit and intent.group_by and intent.group_by != MONTH:
        parts.append(f"(top {intent.limit})")
    return " ".join(parts)


# ---------------------------------------------- grounded summary ---------

def summarize(result: dict, intent: QueryIntent) -> str:
    """A plain-English answer, templated from the ACTUAL result numbers."""
    sub = result.get("subtype")
    metric_label = (intent.metric or "records").replace("_", " ")
    agg_word = {"sum": "Total", "avg": "Average", "min": "Minimum",
                "max": "Maximum", "count": "Count"}[intent.aggregation]

    if result["kind"] == "scalar":
        v = result["value"]
        if v is None:
            return "No matching rows were found for that question."
        return f"{agg_word} {metric_label} is {format_value(v, sub)}."

    data = result["data"]
    if not data:
        return "No matching rows were found for that question."

    if result["kind"] == "series":
        vals = [d["value"] or 0 for d in data]
        hi = max(data, key=lambda d: d["value"] or 0)
        lo = min(data, key=lambda d: d["value"] or 0)
        last = data[-1]
        return (f"{agg_word} {metric_label} by month ranges from {format_value(lo['value'], sub)} "
                f"({lo['label']}) to {format_value(hi['value'], sub)} ({hi['label']}); "
                f"latest is {format_value(last['value'], sub)} in {last['label']}.")

    # grouped
    top = data[0]
    line = f"{top['label']} leads with {format_value(top['value'], sub)} ({agg_word.lower()} {metric_label})"
    if len(data) > 1:
        line += f", followed by {data[1]['label']} ({format_value(data[1]['value'], sub)})"
    return line + "."


def answer_data_question(con, workspace_id: str, dataset_id: str, question: str,
                         llm: LLM | None = None, user_id: str | None = None) -> dict:
    schema = build_schema(con, workspace_id, dataset_id, user_id)
    intent = question_to_intent(question, schema, llm=llm)
    result = execute_intent(con, workspace_id, dataset_id, intent, user_id)
    result["answer"] = summarize(result, intent)
    result["question"] = question
    return result
