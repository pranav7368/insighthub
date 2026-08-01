"""The golden question set.

Each case pins a natural-language question to the answer the *data* gives —
computed independently of the app, from the same rows — so the benchmark scores
whether InsightHub's grounding pipeline reaches the truth, not whether it
agrees with itself.

`expect_abstain` cases are as important as the answerable ones. A tool that
answers everything is worse than one that knows its limits: the industry's
failure mode is a plausible, syntactically valid, *wrong* number that nobody
catches until a decision is made on it. Refusing is a correct outcome here and
is scored as one.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    # exact expected scalar, when the question has one true answer
    expect_value: float | None = None
    # or the label that must rank first, for grouped questions
    expect_top_label: str | None = None
    # a question the data genuinely cannot answer — refusing is the pass
    expect_abstain: bool = False
    # substrings the emitted SQL must contain (proves it did the real work)
    expect_sql_contains: tuple[str, ...] = ()
    note: str = ""


# The fixture every case is scored against. Small enough to verify by hand,
# which is the point: an expected value nobody can check is not a benchmark.
ROWS = [
    # date,        region,  product,  channel,  revenue, units
    ("2025-01-05", "North", "Widget", "Online",  1000, 10),
    ("2025-01-18", "North", "Gadget", "Retail",   500,  5),
    ("2025-02-07", "South", "Widget", "Online",  2000, 25),
    ("2025-02-21", "South", "Gadget", "Retail",  1500, 12),
    ("2025-03-09", "East",  "Widget", "Online",  3000, 30),
    ("2025-03-22", "East",  "Gadget", "Online",   250,  2),
    ("2025-04-11", "North", "Widget", "Retail",  1250, 11),
    ("2025-04-26", "West",  "Gadget", "Online",   750,  6),
]
HEADERS = ["date", "region", "product", "channel", "revenue", "units"]

# Independently computed from ROWS above — deliberately not derived by calling
# the app, or the benchmark would be marking its own homework.
TOTAL_REVENUE = 10250.0      # 1000+500+2000+1500+3000+250+1250+750
TOTAL_UNITS = 101.0          # 10+5+25+12+30+2+11+6
EAST_REVENUE = 3250.0        # 3000+250
ONLINE_REVENUE = 7000.0      # 1000+2000+3000+250+750
WIDGET_REVENUE = 7250.0      # 1000+2000+3000+1250


CASES: tuple[Case, ...] = (
    Case(
        id="total_revenue",
        question="What is the total revenue?",
        expect_value=TOTAL_REVENUE,
        expect_sql_contains=("sum", "revenue"),
    ),
    Case(
        id="total_units",
        question="How many units were sold in total?",
        expect_value=TOTAL_UNITS,
        expect_sql_contains=("sum", "units"),
    ),
    Case(
        id="revenue_by_region_top",
        question="Which region has the highest revenue?",
        expect_top_label="South",
        expect_sql_contains=("region",),
        note="South 3500 > East 3250 > North 2750 > West 750",
    ),
    Case(
        id="revenue_for_east",
        question="What is the total revenue for East?",
        expect_value=EAST_REVENUE,
        expect_sql_contains=("region",),
    ),
    Case(
        id="online_revenue",
        question="What is the revenue from the Online channel?",
        expect_value=ONLINE_REVENUE,
        expect_sql_contains=("channel",),
    ),
    Case(
        id="widget_revenue",
        question="How much revenue came from Widget?",
        expect_value=WIDGET_REVENUE,
        expect_sql_contains=("product",),
    ),
    Case(
        id="average_revenue",
        question="What is the average revenue?",
        expect_value=round(TOTAL_REVENUE / len(ROWS), 4),
        expect_sql_contains=("avg", "revenue"),
    ),
    Case(
        id="row_count",
        question="How many records are there?",
        expect_value=float(len(ROWS)),
        expect_sql_contains=("count",),
    ),
    # --- questions the data cannot answer: refusing is the correct behaviour --
    Case(
        id="absent_column_profit",
        question="What is the total profit margin?",
        expect_abstain=True,
        note="there is no profit or margin column — inventing one is the failure mode",
    ),
    Case(
        id="absent_entity",
        question="What is the revenue for Antarctica?",
        expect_abstain=True,
        note="a region that does not exist must not silently return 0 as if it were a fact",
    ),
)


def _verify_constants() -> None:
    """Recompute the hand-written constants from ROWS at import time.

    Expected values are written out longhand above so a human can check them —
    and a human wrote one of them wrong the first time (East vs South). This
    keeps the ledger honest without giving up the readability.
    """
    idx = {name: i for i, name in enumerate(HEADERS)}
    rev = lambda r: float(r[idx["revenue"]])          # noqa: E731

    assert sum(rev(r) for r in ROWS) == TOTAL_REVENUE
    assert sum(float(r[idx["units"]]) for r in ROWS) == TOTAL_UNITS
    assert sum(rev(r) for r in ROWS if r[idx["region"]] == "East") == EAST_REVENUE
    assert sum(rev(r) for r in ROWS if r[idx["channel"]] == "Online") == ONLINE_REVENUE
    assert sum(rev(r) for r in ROWS if r[idx["product"]] == "Widget") == WIDGET_REVENUE

    by_region: dict[str, float] = {}
    for row in ROWS:
        by_region[row[idx["region"]]] = by_region.get(row[idx["region"]], 0.0) + rev(row)
    top = max(by_region, key=by_region.get)
    expected_top = next(c.expect_top_label for c in CASES if c.id == "revenue_by_region_top")
    assert top == expected_top, f"top region is {top}, case says {expected_top}"


_verify_constants()


def csv_bytes() -> bytes:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    writer.writerows(ROWS)
    return buf.getvalue().encode()
