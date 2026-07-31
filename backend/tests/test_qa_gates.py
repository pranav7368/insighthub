"""Q&A citation gates 2-4 and the abstention path (mocked composer/verifier)."""

import json

import pytest

from app.qa.engine import answer_question
from app.qa.gates import Claim, apply_number_gate, claim_passes_number_gate, validate_claims_schema
from app.qa.llm import HashingEmbedder


# ---- Gate 2 ----

def test_gate2_empty_evidence_fails():
    parsed = {"claims": [{"text": "grew", "evidence": []}, {"text": "grew 12%", "evidence": ["c1"]}]}
    claims, rejected = validate_claims_schema(parsed, {"c1"})
    assert rejected == 1 and len(claims) == 1


def test_gate2_unknown_evidence_fails():
    claims, rejected = validate_claims_schema({"claims": [{"text": "x", "evidence": ["ghost"]}]}, {"c1"})
    assert claims == [] and rejected == 1


# ---- Gate 3 ----

TEXT = {"c1": "Revenue grew 12% reaching $500,000 total."}


def test_gate3_accepts_numbers_in_cited_chunk():
    assert claim_passes_number_gate(Claim("Revenue grew 12%.", ["c1"]), TEXT)[0]


def test_gate3_comma_canonicalization():
    assert claim_passes_number_gate(Claim("Total was 500000.", ["c1"]), TEXT)[0]


def test_gate3_rejects_fabricated_number():
    ok, reason = claim_passes_number_gate(Claim("Revenue grew 45%.", ["c1"]), TEXT)
    assert not ok and "45" in reason


def test_gate3_rejects_number_from_uncited_chunk():
    text = {**TEXT, "c2": "Churn was 8%."}
    assert not claim_passes_number_gate(Claim("Churn was 8%.", ["c1"]), text)[0]


# ---- full path (mock LLM) ----

class ScriptedLLM:
    def __init__(self, composer, verifier=None):
        self.composer, self.verifier = composer, verifier or {"verdicts": []}
        self.verifier_called = False

    def complete(self, prompt, system="", temperature=None, max_tokens=4096):
        if "# ROLE: composer" in prompt:
            return json.dumps(self.composer)
        if "# ROLE: verifier" in prompt:
            self.verifier_called = True
            return json.dumps(self.verifier)
        raise AssertionError("unexpected role")


@pytest.fixture()
def seeded(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("""INSERT INTO datasets
        (dataset_id, workspace_id, name, source_file, kind, table_name, row_count, char_count)
        VALUES ('d1', 'ws_a', 'Report', 'r.txt', 'document', NULL, 0, 100)""")
    con.execute("INSERT INTO chunks VALUES ('c1', 'ws_a', 'd1', 1, 'page 1', 'Revenue grew 12% reaching $500,000 total.')")
    emb = HashingEmbedder()
    con.execute("INSERT INTO chunk_embeddings VALUES ('c1', 'ws_a', ?)", [emb.encode(["Revenue grew 12%"])[0].tolist()])
    return con


GOOD = {"text": "Revenue grew 12% reaching $500,000 total.", "evidence": ["c1"], "type": "fact"}


def test_ask_happy_path(seeded):
    llm = ScriptedLLM(
        {"claims": [GOOD], "confidence": "high", "abstained": False},
        {"verdicts": [{"index": 0, "verdict": "SUPPORTED", "reason": "ok"}]},
    )
    ans = answer_question(seeded, "ws_a", "How did revenue do?", llm=llm, embedder=HashingEmbedder())
    assert not ans.abstained and len(ans.claims) == 1 and llm.verifier_called


def test_ask_verifier_strips_unsupported(seeded):
    bogus = {"text": "Revenue will grow forever.", "evidence": ["c1"], "type": "other"}
    llm = ScriptedLLM(
        {"claims": [GOOD, bogus], "confidence": "high", "abstained": False},
        {"verdicts": [{"index": 0, "verdict": "SUPPORTED", "reason": "ok"},
                      {"index": 1, "verdict": "UNSUPPORTED", "reason": "speculation"}]},
    )
    ans = answer_question(seeded, "ws_a", "How did revenue do?", llm=llm, embedder=HashingEmbedder())
    assert len(ans.claims) == 1 and ans.claims_removed_by_verifier == 1 and ans.confidence == "medium"


def test_ask_number_gate_end_to_end(seeded):
    fabricated = {"text": "Revenue grew 999%.", "evidence": ["c1"], "type": "fact"}
    llm = ScriptedLLM({"claims": [fabricated], "confidence": "high", "abstained": False})
    ans = answer_question(seeded, "ws_a", "How did revenue do?", llm=llm, embedder=HashingEmbedder())
    assert ans.abstained and ans.claims_removed_by_number_gate == 1 and not llm.verifier_called
