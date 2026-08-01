"""Provider-agnostic LLM dispatch + #4 AI narrative (grounded) + number gate."""

import csv
import io
import json

import pytest

from app.analytics.narrative import build_facts, generate_narrative
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    rows = [["date", "branch", "revenue"]]
    for m in range(1, 13):
        rows.append([f"2025-{m:02d}-05", "Delhi", str(1000 + 100 * m)])
        rows.append([f"2025-{m:02d}-06", "Mumbai", str(400 + 20 * m)])
    res = ingest_upload(con, "ws_a", "s.csv", _csv(rows))
    return con, "ws_a", res.dataset_id


# ---- provider dispatch (no network) ----

def test_provider_dispatch_offline(monkeypatch):
    from app.core import config
    from app.qa import llm
    monkeypatch.setattr(config, "OFFLINE", True)
    assert llm.resolve_provider() == "offline"
    assert type(llm.get_llm()).__name__ == "OfflineLLM"


def test_provider_dispatch_openai_compatible(monkeypatch):
    from app.core import config
    from app.qa import llm
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-test-not-real")
    obj = llm.get_llm()  # constructs client, no network call
    assert type(obj).__name__ == "OpenAICompatibleLLM"
    assert llm.provider_status()["provider"] == "openai"


def test_provider_status_reports_model(monkeypatch):
    from app.core import config
    from app.qa import llm
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "MODEL", "")
    assert llm.provider_status() == {"provider": "ollama", "model": "llama3.1"}


# ---- narrative (offline deterministic) ----

def test_narrative_offline_produces_headline_and_actions(ds):
    con, ws, dsid = ds
    result = generate_narrative(con, ws, dsid)  # offline via conftest IH_OFFLINE=1
    assert result["headline"]
    assert len(result["recommendations"]) >= 1
    assert all(r["priority"] in ("high", "medium", "low") for r in result["recommendations"])
    assert result["provider"] == "offline"
    # offline only reuses computed figures -> nothing unverified
    assert result["unverified_numbers"] == []


# ---- number gate flags a hallucinated figure ----

def test_narrative_number_gate_flags_fabricated_number(ds):
    con, ws, dsid = ds

    class FabricatingLLM:
        def complete(self, prompt, system="", temperature=None, max_tokens=4096):
            return json.dumps({
                "headline": "Revenue soared 9999% overnight",   # 9999 is not in facts
                "narrative": "Everything is up.",
                "recommendations": [{"title": "Scale up", "detail": "Add capacity.", "priority": "high"}],
            })

    result = generate_narrative(con, ws, dsid, llm=FabricatingLLM())
    assert any("9999" in n for n in result["unverified_numbers"])


def test_build_facts_has_no_raw_rows(ds):
    con, ws, dsid = ds
    from app.analytics.engine import compute_dashboard
    facts = build_facts(compute_dashboard(con, ws, dsid))
    assert set(facts) & {"kpis", "insights"}
    # facts must be compact - no per-row data leaks to the LLM
    assert "points" not in json.dumps(facts)
