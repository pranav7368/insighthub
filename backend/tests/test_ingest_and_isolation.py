"""Ingestion across formats + the multi-tenant isolation guarantee."""

import csv
import io

import pytest

from app.analytics.engine import DatasetNotFound, compute_dashboard
from app.ingest.pipeline import ingest_upload
from app.qa.engine import answer_question
from app.qa.llm import HashingEmbedder


def csv_bytes(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SALES = [
    ["date", "branch", "revenue", "units_sold"],
    ["2025-01-05", "Delhi", "1000", "10"],
    ["2025-01-06", "Mumbai", "2000", "20"],
    ["2025-02-05", "Delhi", "1500", "15"],
]


def test_structured_ingest_detects_roles(con, workspace):
    result = ingest_upload(con, workspace, "sales.csv", csv_bytes(SALES))
    assert result.kind == "structured"
    assert result.row_count == 3
    roles = {c.name: c.role for c in result.columns}
    assert roles["date"] == "date"
    assert roles["branch"] == "dimension"
    assert roles["revenue"] == "measure"
    assert roles["units_sold"] == "measure"


def test_ingest_sanitizes_malicious_column_names(con, workspace):
    rows = [['"; DROP TABLE users; --', "amount"], ["x", "5"]]
    # ingestion must not blow up and the users table must survive
    ingest_upload(con, workspace, "evil.csv", csv_bytes(rows))
    assert con.execute("SELECT count(*) FROM users").fetchone()[0] == 0  # table still exists


def test_document_ingest_creates_chunks(con, workspace):
    text = ("Return Policy\n\nCustomers may return any unopened product within 30 days "
            "for a full refund.\n\nRefunds are processed within 5 to 7 business days.").encode()
    result = ingest_upload(con, workspace, "policy.txt", text)
    assert result.kind == "document"
    assert result.chunks >= 1


def test_dashboard_computes_kpis(con, workspace):
    result = ingest_upload(con, workspace, "sales.csv", csv_bytes(SALES))
    dash = compute_dashboard(con, workspace, result.dataset_id)
    revenue_kpi = next(k for k in dash["kpis"] if k["column"] == "revenue")
    assert revenue_kpi["total"] == 4500
    assert dash["breakdowns"]["branch"]["data"][0]["name"] == "Delhi"  # 2500 > 2000
    assert len(dash["trend"]) == 2  # Jan + Feb


# ---------------------------------------------- TENANT ISOLATION ---------

def test_tenant_cannot_read_another_tenants_dashboard(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    a = ingest_upload(con, "ws_a", "sales.csv", csv_bytes(SALES))

    # tenant B asking for tenant A's dataset_id must be refused
    with pytest.raises(DatasetNotFound):
        compute_dashboard(con, "ws_b", a.dataset_id)
    # tenant A can read it
    assert compute_dashboard(con, "ws_a", a.dataset_id)["row_count_filtered"] == 3


def test_qa_only_sees_own_workspace_chunks(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    ingest_upload(con, "ws_a", "secret.txt",
                  b"The launch code for project atlas is codename bluewhale seventeen.")

    embedder = HashingEmbedder()
    # tenant B asks a question whose answer only exists in tenant A's docs
    answer = answer_question(con, "ws_b", "What is the launch code for project atlas?", embedder=embedder)
    assert answer.abstained  # B has no documents at all -> nothing to answer from
    # tenant A can retrieve it
    answer_a = answer_question(con, "ws_a", "What is the launch code for project atlas?", embedder=embedder)
    assert not answer_a.abstained
    assert any("bluewhale" in c.text for c in answer_a.claims)
