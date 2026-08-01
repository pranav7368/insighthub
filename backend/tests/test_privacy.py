"""PII detection and masking.

Masking rides on the same relation rewrite as row-level security, so the tests
that matter are the end-to-end ones: a non-admin must not be able to recover a
raw value through *any* read path, including the ones that were never written
with PII in mind (filter dropdowns, CSV export, Ask).
"""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.analytics.privacy import (
    EMAIL, NATIONAL_ID, PERSON_NAME, PHONE, detect_pii, mask_expression,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pii_test.duckdb")
    from app.main import app

    return TestClient(app)


PEOPLE = [
    ["date", "customer_name", "email", "phone", "aadhaar", "region", "revenue"],
    ["2025-01-05", "Priya Sharma", "priya.sharma@acme.com", "9876543210", "123456789012", "North", "1000"],
    ["2025-01-06", "Raj Patel", "raj.patel@corp.io", "9998887776", "234567890123", "South", "2000"],
    ["2025-02-07", "Anita Desai", "anita@example.org", "9123456780", "345678901234", "East", "3000"],
    ["2025-02-08", "Vikram Rao", "vikram.rao@acme.com", "9012345678", "456789012345", "North", "4000"],
    ["2025-03-09", "Meera Iyer", "meera@corp.io", "9345678901", "567890123456", "South", "5000"],
]

RAW_VALUES = ["priya.sharma@acme.com", "9876543210", "123456789012", "Priya Sharma"]


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def env(client):
    admin = client.post("/api/auth/signup", json={
        "email": "boss@example.com", "password": "supersecret1", "workspace_name": "Acme",
    }).json()["access_token"]
    ds = client.post("/api/datasets/upload",
                     files={"file": ("people.csv", _csv(PEOPLE), "text/csv")},
                     headers=auth(admin)).json()["dataset_id"]
    client.post("/api/members", json={"email": "analyst@example.com", "role": "editor",
                                      "password": "supersecret1"}, headers=auth(admin))
    editor = client.post("/api/auth/login", json={
        "email": "analyst@example.com", "password": "supersecret1",
    }).json()["access_token"]
    return {"client": client, "admin": admin, "editor": editor, "dataset_id": ds}


# ------------------------------------------------------------ detection ---

@pytest.mark.parametrize("column,expected", [
    ("email", EMAIL), ("customer_email", EMAIL), ("e_mail", EMAIL),
    ("phone", PHONE), ("mobile", PHONE), ("phone_number", PHONE),
    ("aadhaar", NATIONAL_ID), ("pan_number", NATIONAL_ID), ("ssn", NATIONAL_ID),
    ("customer_name", PERSON_NAME), ("patient_name", PERSON_NAME),
])
def test_detects_pii_by_column_name(column, expected):
    assert detect_pii(column) == expected


@pytest.mark.parametrize("column", ["revenue", "region", "product_name", "order_id", "date"])
def test_does_not_flag_ordinary_columns(column):
    assert detect_pii(column) is None


def test_product_name_is_not_a_person():
    """A blunt 'name' substring match would mangle every catalogue column."""
    assert detect_pii("product_name") is None
    assert detect_pii("brand_name") is None


def test_detects_pii_from_values_when_the_name_hides_it():
    assert detect_pii("col_a", [f"user{i}@example.com" for i in range(10)]) == EMAIL
    assert detect_pii("col_b", [str(100000000000 + i) for i in range(10)]) == NATIONAL_ID


def test_values_that_merely_look_numeric_are_not_pii():
    assert detect_pii("amount", [str(i) for i in range(10)]) is None


@pytest.mark.parametrize("dates", [
    ["2025-01-05", "2025-02-11", "2025-03-27", "2024-12-31", "2025-06-02", "2025-07-14"],
    ["05/01/2025", "11/02/2025", "27/03/2025", "31/12/2024", "02/06/2025", "14/07/2025"],
])
def test_dates_are_not_mistaken_for_phone_numbers(dates):
    """An ISO date is ten digits with separators — the shape a loose phone
    pattern accepts. Masking the date column would break every trend."""
    assert detect_pii("col_x", dates) is None


def test_mask_expression_handles_null_and_keeps_shape():
    expr = mask_expression('"email"', EMAIL)
    assert "IS NULL THEN NULL" in expr          # NULL stays NULL, never '***'
    assert "split_part" in expr                 # domain preserved for grouping


# ------------------------------------------------------------- policies ---

def test_pii_columns_are_detected_and_masked_on_upload(env):
    policies = env["client"].get(f"/api/datasets/{env['dataset_id']}/privacy",
                                 headers=auth(env["admin"])).json()
    found = {p["column_name"]: p for p in policies}
    assert set(found) == {"customer_name", "email", "phone", "aadhaar"}
    assert all(p["masked"] for p in policies)
    assert found["email"]["pii_kind"] == EMAIL
    assert found["aadhaar"]["pii_kind"] == NATIONAL_ID


def test_pii_column_is_never_left_as_a_measure(env):
    """A 12-digit id would otherwise be summed into a nonsense KPI — and a
    masked (text) value cannot be aggregated at all."""
    schema = env["client"].get(f"/api/datasets/{env['dataset_id']}/schema",
                               headers=auth(env["admin"])).json()
    roles = {c["name"]: c["role"] for c in schema}
    assert roles["aadhaar"] != "measure"
    assert roles["revenue"] == "measure"      # ordinary measures are untouched


def test_only_admins_read_or_change_the_policy(env):
    ds = env["dataset_id"]
    c = env["client"]
    assert c.get(f"/api/datasets/{ds}/privacy", headers=auth(env["editor"])).status_code == 403
    assert c.patch(f"/api/datasets/{ds}/privacy",
                   json={"column_name": "email", "masked": False},
                   headers=auth(env["editor"])).status_code == 403


def test_unknown_column_rejected(env):
    r = env["client"].patch(f"/api/datasets/{env['dataset_id']}/privacy",
                            json={"column_name": "nope", "masked": True},
                            headers=auth(env["admin"]))
    assert r.status_code == 400


# ------------------------------------------------------------- masking ----

def _blob(response):
    return response.text


def test_admin_sees_raw_values(env):
    body = _blob(env["client"].get(f"/api/datasets/{env['dataset_id']}/export.csv",
                                   headers=auth(env["admin"])))
    for raw in RAW_VALUES:
        assert raw in body


def test_non_admin_csv_export_is_masked(env):
    body = _blob(env["client"].get(f"/api/datasets/{env['dataset_id']}/export.csv",
                                   headers=auth(env["editor"])))
    for raw in RAW_VALUES:
        assert raw not in body
    assert "pr***@acme.com" in body          # shape preserved, identity removed
    assert "******3210" in body


def test_dashboard_breakdowns_and_filters_are_masked(env):
    dash = env["client"].get(f"/api/datasets/{env['dataset_id']}/dashboard",
                             headers=auth(env["editor"]))
    blob = _blob(dash)
    for raw in RAW_VALUES:
        assert raw not in blob


def test_ask_answers_are_masked(env):
    r = env["client"].post(f"/api/datasets/{env['dataset_id']}/query",
                           json={"question": "revenue by email"}, headers=auth(env["editor"]))
    assert r.status_code == 200
    for raw in RAW_VALUES:
        assert raw not in _blob(r)


def test_quality_report_does_not_leak_values(env):
    r = env["client"].get(f"/api/datasets/{env['dataset_id']}/quality",
                          headers=auth(env["editor"]))
    for raw in RAW_VALUES:
        assert raw not in _blob(r)


def test_masking_does_not_disturb_the_numbers(env):
    """Redaction must change what values look like, never what they add up to."""
    c, ds = env["client"], env["dataset_id"]
    as_admin = c.get(f"/api/datasets/{ds}/dashboard", headers=auth(env["admin"])).json()
    as_editor = c.get(f"/api/datasets/{ds}/dashboard", headers=auth(env["editor"])).json()
    assert as_admin["kpis"][0]["total"] == as_editor["kpis"][0]["total"] == 15000
    assert as_admin["row_count_filtered"] == as_editor["row_count_filtered"]


def test_unmasking_a_column_restores_it_for_everyone(env):
    c, ds = env["client"], env["dataset_id"]
    assert c.patch(f"/api/datasets/{ds}/privacy",
                   json={"column_name": "email", "masked": False},
                   headers=auth(env["admin"])).status_code == 200

    body = _blob(c.get(f"/api/datasets/{ds}/export.csv", headers=auth(env["editor"])))
    assert "priya.sharma@acme.com" in body       # the source data was never altered
    assert "9876543210" not in body              # other columns stay masked


def test_masking_a_previously_clean_column(env):
    """An admin can mark something the detector missed."""
    c, ds = env["client"], env["dataset_id"]
    c.patch(f"/api/datasets/{ds}/privacy",
            json={"column_name": "region", "masked": True, "pii_kind": PERSON_NAME},
            headers=auth(env["admin"]))
    body = _blob(c.get(f"/api/datasets/{ds}/export.csv", headers=auth(env["editor"])))
    assert "North" not in body and "N*****" in body


def test_share_links_mask_for_their_audience(env):
    """A public link is the least trusted surface there is."""
    c, ds = env["client"], env["dataset_id"]
    token = c.post(f"/api/datasets/{ds}/shares", json={"label": "public"},
                   headers=auth(env["editor"])).json()["token"]
    for raw in RAW_VALUES:
        assert raw not in _blob(c.get(f"/api/public/{token}/dashboard"))
