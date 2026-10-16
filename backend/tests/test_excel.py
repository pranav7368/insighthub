"""Excel ingest: calamine reads workbooks, openpyxl is the fallback, and both
produce the same dataset."""

import io
from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from app.analytics.engine import compute_dashboard
from app.ingest import pipeline
from app.ingest.pipeline import ingest_upload


def _workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["order_date", "region", "units", "revenue", "note"])
    rows = [
        (datetime(2025, 1, 5), "North", 3, 120.5, None),
        (datetime(2025, 1, 20), "South", 1, 40.0, "promo"),
        (datetime(2025, 2, 3), None, 5, 210.25, None),
        (datetime(2025, 2, 17), "North", 2, 80.0, None),
    ]
    for r in rows:
        ws.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.fixture()
def ws(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_x', 'X')")
    return con


def test_workbook_ingests_with_types_and_blanks(ws):
    res = ingest_upload(ws, "ws_x", "sales.xlsx", _workbook())
    assert res.kind == "structured" and res.row_count == 4
    roles = {c.name: c.role for c in res.columns}
    assert roles["order_date"] == "date" and roles["region"] == "dimension"
    assert roles["revenue"] == "measure"
    dash = compute_dashboard(ws, "ws_x", res.dataset_id)
    revenue = next(k for k in dash["kpis"] if k["column"] == "revenue")
    assert revenue["total"] == pytest.approx(450.75)


def test_both_engines_read_the_same_frame():
    data = _workbook()
    fast = pd.read_excel(io.BytesIO(data), engine="calamine")
    slow = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    pd.testing.assert_frame_equal(fast, slow)


def test_falls_back_to_openpyxl_when_calamine_cannot_read(ws, monkeypatch):
    real = pd.read_excel
    engines = []

    def flaky(buf, *args, engine=None, **kw):
        engines.append(engine)
        if engine == "calamine":
            raise ValueError("unsupported workbook feature")
        return real(buf, *args, engine=engine, **kw)

    monkeypatch.setattr(pipeline.pd, "read_excel", flaky)
    res = ingest_upload(ws, "ws_x", "sales.xlsx", _workbook())
    assert engines == ["calamine", "openpyxl"] and res.row_count == 4
