"""The grounding benchmark.

Everyone in this category claims their AI analyst is accurate. The published
numbers say otherwise: 50–89% on real questions, and one study measured 86% in
a demo against 6% on real data with the *same model* — the accuracy lives in
the architecture, not the model.

So this suite exists to hold us to a number instead of a claim. It runs the
golden set through the real HTTP endpoint, in offline mode (deterministic
fallback, no LLM key needed, no network), and scores four things:

  correctness  — did the answer match the value computed independently?
  grounding    — did every answer come with the SQL that produced it?
  abstention   — did it refuse the questions the data cannot answer?
  no-invention — did it ever emit a number with no query behind it?

The last two are the ones that matter commercially. A wrong number that looks
right is the failure this product exists to prevent, so `test_never_invents`
is the test to keep green above all others.

Run just this suite:  pytest tests/eval -q -s
"""

import json

import pytest
from fastapi.testclient import TestClient

from .golden import CASES, csv_bytes


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    from app.core import config

    path = tmp_path_factory.mktemp("eval") / "bench.duckdb"
    original = config.DB_PATH
    config.DB_PATH = path
    from app.main import app

    client = TestClient(app)
    token = client.post("/api/auth/signup", json={
        "email": "bench@example.com", "password": "supersecret1", "workspace_name": "Bench",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    dataset_id = client.post(
        "/api/datasets/upload",
        files={"file": ("bench.csv", csv_bytes(), "text/csv")},
        headers=headers,
    ).json()["dataset_id"]

    yield client, headers, dataset_id
    config.DB_PATH = original


def ask(api, question):
    client, headers, dataset_id = api
    return client.post(f"/api/datasets/{dataset_id}/query",
                       json={"question": question}, headers=headers)


def _numbers_in(payload) -> list[float]:
    """Every numeric value the answer surfaces to the user."""
    found = []
    if payload.get("kind") == "scalar" and payload.get("value") is not None:
        found.append(float(payload["value"]))
    for point in payload.get("data") or []:
        if point.get("value") is not None:
            found.append(float(point["value"]))
    return found


def _refused(response) -> bool:
    """A refusal is either a 4xx or an answered-but-empty result."""
    if response.status_code >= 400:
        return True
    body = response.json()
    if body.get("kind") == "scalar":
        return body.get("value") in (None, 0) and not body.get("sql")
    return not (body.get("data") or [])


# --------------------------------------------------------------- scoring ---

@pytest.mark.parametrize("case", [c for c in CASES if not c.expect_abstain],
                         ids=lambda c: c.id)
def test_answerable_questions_are_correct(api, case):
    response = ask(api, case.question)
    assert response.status_code == 200, response.text
    body = response.json()

    if case.expect_value is not None:
        values = _numbers_in(body)
        assert values, f"{case.id}: no number returned"
        assert any(abs(v - case.expect_value) < 0.01 for v in values), (
            f"{case.id}: expected {case.expect_value}, got {values}"
        )

    if case.expect_top_label is not None:
        data = body.get("data") or []
        assert data, f"{case.id}: no grouped rows returned"
        top = max(data, key=lambda d: d.get("value") or 0)
        assert top["label"] == case.expect_top_label, (
            f"{case.id}: expected {case.expect_top_label} on top, got {top['label']}"
        )


@pytest.mark.parametrize("case", [c for c in CASES if not c.expect_abstain],
                         ids=lambda c: c.id)
def test_every_answer_shows_its_sql(api, case):
    """The trust claim, mechanically. An answer without a query behind it is
    exactly the thing we tell customers we never do."""
    body = ask(api, case.question).json()
    sql = (body.get("sql") or "").lower()
    assert sql, f"{case.id}: answered with no SQL to verify"
    for fragment in case.expect_sql_contains:
        assert fragment.lower() in sql, (
            f"{case.id}: SQL does not reference {fragment!r} — {sql}"
        )


@pytest.mark.parametrize("case", [c for c in CASES if c.expect_abstain],
                         ids=lambda c: c.id)
def test_unanswerable_questions_are_refused(api, case):
    """Refusing is a feature. Returning a confident 0 for a column that does
    not exist is the industry's characteristic failure."""
    assert _refused(ask(api, case.question)), (
        f"{case.id}: should have refused — {case.note}"
    )


def test_never_invents_a_number(api):
    """The load-bearing test. Every number shown must come from a query."""
    offenders = []
    for case in CASES:
        response = ask(api, case.question)
        if response.status_code >= 400:
            continue
        body = response.json()
        if _numbers_in(body) and not body.get("sql"):
            offenders.append(case.id)
    assert not offenders, f"numbers shown with no SQL behind them: {offenders}"


def test_scorecard(api, capsys):
    """Prints the scorecard and enforces a floor.

    The floor is a ratchet: when the score improves, raise it. It must never be
    lowered to make a build pass — that is how a trust product quietly stops
    being one.
    """
    results = {"correct": 0, "grounded": 0, "abstained": 0, "total": len(CASES)}
    failures = []

    for case in CASES:
        response = ask(api, case.question)
        if case.expect_abstain:
            if _refused(response):
                results["abstained"] += 1
            else:
                failures.append(f"{case.id}: answered an unanswerable question")
            continue

        if response.status_code != 200:
            failures.append(f"{case.id}: {response.status_code}")
            continue
        body = response.json()
        if body.get("sql"):
            results["grounded"] += 1

        ok = False
        if case.expect_value is not None:
            ok = any(abs(v - case.expect_value) < 0.01 for v in _numbers_in(body))
        elif case.expect_top_label is not None:
            data = body.get("data") or []
            ok = bool(data) and max(data, key=lambda d: d.get("value") or 0)["label"] == case.expect_top_label
        if ok:
            results["correct"] += 1
        else:
            failures.append(f"{case.id}: wrong answer")

    answerable = sum(1 for c in CASES if not c.expect_abstain)
    unanswerable = len(CASES) - answerable
    score = {
        "correctness": f"{results['correct']}/{answerable}",
        "grounded_with_sql": f"{results['grounded']}/{answerable}",
        "correct_abstentions": f"{results['abstained']}/{unanswerable}",
        "failures": failures,
    }
    with capsys.disabled():
        print("\n--- InsightHub grounding benchmark ---")
        print(json.dumps(score, indent=2))

    # ratchet: raise these as the pipeline improves, never lower them
    assert results["grounded"] == answerable, "every answer must ship its SQL"
    assert results["abstained"] == unanswerable, "must refuse what it cannot answer"
    assert results["correct"] >= answerable, f"correctness regressed: {failures}"
