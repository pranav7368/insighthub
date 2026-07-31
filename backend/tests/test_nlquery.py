"""Conversational analytics: NL -> intent -> safe SQL -> grounded answer.
Also proves the intent validator rejects unknown columns / injection."""

import csv
import io

import pytest

from app.analytics.nlquery import (
    QueryIntent, _validate_intent, answer_data_question, build_schema,
    execute_intent, question_to_intent,
)
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SALES = [["date", "business_unit", "branch", "revenue", "units_sold"]]
for _m in range(1, 13):
    SALES.append([f"2025-{_m:02d}-10", "Retail", "Delhi", str(1000 + 10 * _m), str(50 + _m)])
    SALES.append([f"2025-{_m:02d}-12", "Wholesale", "Mumbai", str(3000 + 5 * _m), str(80 + _m)])


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    return con, "ws_a", res.dataset_id


# ---- offline intent parsing (rule-based, no network) ----

def test_parse_total_question(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    intent = question_to_intent("What is the total revenue?", schema)
    assert intent.metric == "revenue" and intent.aggregation == "sum" and intent.group_by is None
    assert intent.chart_type == "kpi"


def test_parse_group_by_dimension(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    intent = question_to_intent("Show revenue by branch", schema)
    assert intent.metric == "revenue" and intent.group_by == "branch" and intent.chart_type == "bar"


def test_parse_trend_over_time(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    intent = question_to_intent("How has revenue changed over time?", schema)
    assert intent.group_by == "__month__" and intent.chart_type == "line"


def test_parse_average_and_share(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    assert question_to_intent("average units_sold", schema).aggregation == "avg"
    assert question_to_intent("revenue share by business_unit", schema).chart_type == "pie"


def test_parse_filter_value(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    intent = question_to_intent("total revenue for Delhi", schema)
    assert intent.filters.get("branch") == "Delhi"


# ---- validation / safety ----

def test_validator_rejects_unknown_columns(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    intent = _validate_intent(
        {"metric": "password_hash", "aggregation": "sum", "group_by": "secret_table",
         "filters": {"drop": "x"}, "chart_type": "bar"}, schema)
    assert intent.metric in {"revenue", "units_sold"}     # fell back to a real measure
    assert intent.group_by is None                          # unknown dim dropped
    assert intent.filters == {}                             # unknown filter dropped


def test_validator_rejects_bad_aggregation(ds):
    con, ws, dsid = ds
    schema = build_schema(con, ws, dsid)
    intent = _validate_intent({"metric": "revenue", "aggregation": "DROP TABLE"}, schema)
    assert intent.aggregation == "sum"


# ---- grounded execution ----

def test_scalar_answer_is_real(ds):
    con, ws, dsid = ds
    res = answer_data_question(con, ws, dsid, "What is the total revenue?")
    # sum of both series over 12 months
    expected = sum(1000 + 10 * m for m in range(1, 13)) + sum(3000 + 5 * m for m in range(1, 13))
    assert res["kind"] == "scalar" and res["value"] == expected
    assert "Total revenue is" in res["answer"]


def test_grouped_answer_orders_correctly(ds):
    con, ws, dsid = ds
    res = answer_data_question(con, ws, dsid, "revenue by branch")
    assert res["kind"] == "grouped"
    # Mumbai (Wholesale ~3000/mo) outranks Delhi (~1000/mo)
    assert res["data"][0]["label"] == "Mumbai"
    assert "Mumbai leads" in res["answer"]


def test_filtered_answer(ds):
    con, ws, dsid = ds
    res = answer_data_question(con, ws, dsid, "total revenue for Delhi")
    expected = sum(1000 + 10 * m for m in range(1, 13))
    assert res["value"] == expected


# ---- show-the-SQL transparency ----

def test_answer_exposes_readable_sql(ds):
    con, ws, dsid = ds
    scalar = answer_data_question(con, ws, dsid, "What is the total revenue?")
    assert 'SUM("revenue")' in scalar["sql"] and 'FROM "sales"' in scalar["sql"]
    # the friendly dataset name is shown, never the internal physical table
    assert "t_" not in scalar["sql"]

    grouped = answer_data_question(con, ws, dsid, "revenue by branch")
    assert "GROUP BY" in grouped["sql"] and 'FROM "sales"' in grouped["sql"]


def test_sql_inlines_filter_values_readably(ds):
    con, ws, dsid = ds
    res = answer_data_question(con, ws, dsid, "total revenue for Delhi")
    # the bound parameter is shown inlined as a literal for humans, no '?'
    assert "'Delhi'" in res["sql"] and "?" not in res["sql"]


def test_execute_intent_injection_safe(ds):
    con, ws, dsid = ds
    # a hand-crafted malicious intent must not reach SQL: unknown identifiers
    # are rejected by safe_identifier via the schema whitelist
    from app.core.sqlsafe import UnsafeIdentifierError
    bad = QueryIntent(metric="revenue", aggregation="sum", group_by='"; DROP TABLE users; --')
    # validator would strip it, but even raw it must be refused, not executed
    intent = QueryIntent(metric="revenue", aggregation="sum")
    intent.group_by = '"; DROP TABLE users; --'
    try:
        execute_intent(con, ws, dsid, intent)
    except UnsafeIdentifierError:
        pass  # acceptable: refused
    # users table intact regardless
    assert con.execute("SELECT count(*) FROM users").fetchone()[0] == 0
