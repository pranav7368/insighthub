"""Industry templates: generators, catalog, and the one-click end-to-end
materialization (dataset + certified metrics + default arranged view)."""

import pytest
from fastapi.testclient import TestClient
from pandas.api.types import is_numeric_dtype

from app.analytics.detect import PERCENT_HINTS, detect_schema
from app.core.sqlsafe import sanitize_identifier
from app.ingest.templates import (
    TEMPLATES, UnknownTemplate, catalog, get_template,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "tpl_test.duckdb")
    from app.main import app

    return TestClient(app)


def signup(client, email, ws="Acme"):
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": "supersecret1", "workspace_name": ws})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


IDS = [t.id for t in TEMPLATES]


# --------------------------------------------------------- generators ------

@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_generator_produces_usable_data(tpl):
    df = tpl.build()
    assert not df.empty
    assert "date" in df.columns
    assert df["date"].nunique() >= 6           # enough months for a trend/forecast
    # a dashboard needs at least one numeric measure and one categorical dimension
    numeric = [c for c in df.columns if is_numeric_dtype(df[c])]
    categorical = [c for c in df.columns if c != "date" and not is_numeric_dtype(df[c])]
    assert numeric and categorical


@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_generator_is_deterministic(tpl):
    assert tpl.build().equals(tpl.build())


@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_counts_are_not_detected_as_percentages(tpl):
    """Guard the shape of the generated numbers, not just their names.

    Sample data with tiny counts (0/1 per row) sits inside the detector's
    fractional 0..1 band, so a headcount column gets rendered as "72.0%". Any
    column the detector calls a percentage must genuinely be a rate.
    """
    for profile in detect_schema(tpl.build()):
        if profile.subtype == "percentage":
            assert any(hint in profile.name.lower() for hint in PERCENT_HINTS), (
                f"{tpl.id}: {profile.name!r} would display as a percentage but is a count"
            )


@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_headline_measure_is_detected_as_a_measure(tpl):
    """The pinned measure must survive detection, or the saved view is stale."""
    roles = {p.name: p.role for p in detect_schema(tpl.build())}
    assert roles.get(tpl.measure) == "measure", f"{tpl.id}: {tpl.measure!r} -> {roles.get(tpl.measure)}"


@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_metric_definitions_reference_real_columns(tpl):
    """A metric naming a column the generator does not emit would be silently
    dropped at load time — catch that here instead."""
    columns = {sanitize_identifier(c) for c in tpl.build().columns}
    for metric in tpl.metrics:
        d = metric.definition
        specs = [d] if metric.kind == "aggregate" else [d["numerator"], d["denominator"]]
        for spec in specs:
            col = spec.get("column")
            if col is not None:
                assert col in columns, f"{tpl.id}/{metric.name} references missing column {col!r}"


# ------------------------------------------------------------ catalog ------

def test_catalog_is_complete_and_serializable():
    cards = catalog()
    assert len(cards) == len(TEMPLATES)
    for card in cards:
        assert card["id"] and card["label"] and card["description"] and card["icon"]
        assert card["highlights"] and card["metrics"]
        assert "build" not in card                     # builders never leak to the client


def test_get_template_is_case_insensitive_and_validates():
    assert get_template("RETAIL").id == "retail"
    with pytest.raises(UnknownTemplate):
        get_template("not_an_industry")


def test_template_ids_are_unique():
    assert len(IDS) == len(set(IDS))


# ----------------------------------------------------------- endpoints -----

def test_catalog_endpoint_requires_auth(client):
    assert client.get("/api/templates").status_code == 401


def test_catalog_endpoint_lists_templates(client):
    token = signup(client, "cat@example.com")
    r = client.get("/api/templates", headers=auth(token))
    assert r.status_code == 200
    assert {c["id"] for c in r.json()} == set(IDS)


def test_unknown_template_is_400(client):
    token = signup(client, "bad@example.com")
    r = client.post("/api/datasets/template", json={"template_id": "crypto"}, headers=auth(token))
    assert r.status_code == 400


@pytest.mark.parametrize("template_id", IDS)
def test_template_builds_dashboard_metrics_and_view(client, template_id):
    tpl = get_template(template_id)
    token = signup(client, f"{template_id}@example.com")

    r = client.post("/api/datasets/template", json={"template_id": template_id}, headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    ds_id = body["dataset_id"]
    assert body["row_count"] > 0 and body["template_id"] == template_id
    # every declared metric must actually be creatable against the generated data
    assert body["metrics"] == len(tpl.metrics)

    dash = client.get(f"/api/datasets/{ds_id}/dashboard", headers=auth(token))
    assert dash.status_code == 200, dash.text
    assert len(dash.json()["kpis"]) >= 1

    # certified metrics compute, and each shows the SQL that produced it
    metrics = client.get(f"/api/datasets/{ds_id}/metrics", headers=auth(token)).json()
    assert {m["name"] for m in metrics} == {m.name for m in tpl.metrics}
    for m in metrics:
        assert m["error"] is None and m["value"] is not None and m["sql"]

    # the default view carries the template's arrangement
    views = client.get(f"/api/datasets/{ds_id}/views", headers=auth(token)).json()
    assert len(views) == 1 and views[0]["is_default"]
    cfg = views[0]["config"]
    assert cfg["section_order"] == list(tpl.section_order)
    assert cfg["hidden_sections"] == list(tpl.hidden_sections)
    # the headline measure must be pinned, and be a column the data really has
    assert cfg["measure"] == tpl.measure
    schema = client.get(f"/api/datasets/{ds_id}/schema", headers=auth(token)).json()
    assert tpl.measure in {c["name"] for c in schema}


def test_sample_endpoint_uses_the_default_template(client):
    """The legacy one-click sample keeps working — and now arrives arranged."""
    token = signup(client, "sample-tpl@example.com")
    r = client.post("/api/datasets/sample", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] > 0 and body["template_id"] == "retail"
    views = client.get(f"/api/datasets/{body['dataset_id']}/views", headers=auth(token)).json()
    assert len(views) == 1 and views[0]["is_default"]


def test_viewer_cannot_load_a_template(client):
    """Creating data is an editor action."""
    token = signup(client, "owner-tpl@example.com")
    client.post("/api/members", json={"email": "v@example.com", "role": "viewer",
                                      "password": "supersecret1"}, headers=auth(token))
    viewer = client.post("/api/auth/login",
                         json={"email": "v@example.com", "password": "supersecret1"}).json()["access_token"]
    r = client.post("/api/datasets/template", json={"template_id": "saas"}, headers=auth(viewer))
    assert r.status_code == 403
