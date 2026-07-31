"""Answer schema + Gate 2 (schema/citation) and Gate 3 (numbers).

Gates are code, not prompts:
  GATE 2 - every claim must cite >=1 chunk_id actually supplied to the
           composer. Empty/unknown evidence => rejected.
  GATE 3 - every numeral in a claim must appear (after canonicalization,
           so "$500,000" matches "500000") in the text of a chunk THAT SAME
           CLAIM cites. A claim can't borrow a number from an uncited chunk.
"""

import re
from dataclasses import asdict, dataclass, field

_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


@dataclass
class Claim:
    text: str
    evidence: list[str]
    type: str = "other"


@dataclass
class Answer:
    question: str
    mode: str = "rag"
    claims: list[Claim] = field(default_factory=list)
    confidence: str = "low"
    abstained: bool = False
    abstention_reason: str | None = None
    claims_removed_by_verifier: int = 0
    claims_removed_by_schema: int = 0
    claims_removed_by_number_gate: int = 0

    def as_dict(self):
        return asdict(self)


def validate_claims_schema(parsed: dict, supplied_ids: set[str]) -> tuple[list[Claim], int]:
    accepted, rejected = [], 0
    raw = parsed.get("claims") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return [], 0
    for item in raw:
        if not isinstance(item, dict):
            rejected += 1
            continue
        text, evidence = item.get("text"), item.get("evidence")
        if not isinstance(text, str) or not text.strip():
            rejected += 1
            continue
        if not isinstance(evidence, list) or not evidence:
            rejected += 1
            continue
        evidence = [str(e) for e in evidence]
        if not all(e in supplied_ids for e in evidence):
            rejected += 1
            continue
        ctype = item.get("type") if item.get("type") in ("quote", "fact", "summary", "other") else "other"
        accepted.append(Claim(text=text.strip(), evidence=evidence, type=ctype))
    return accepted, rejected


def _canon(value: str) -> str:
    cleaned = value.replace(",", "").rstrip("%")
    try:
        return f"{float(cleaned):g}"
    except ValueError:
        return cleaned


def claim_passes_number_gate(claim: Claim, text_by_id: dict[str, str]) -> tuple[bool, str]:
    cited = [text_by_id.get(cid, "") for cid in claim.evidence]
    allowed_raw, allowed_canon = set(), set()
    for text in cited:
        for m in _NUM_RE.finditer(text):
            allowed_raw.add(m.group(0))
            allowed_canon.add(_canon(m.group(0)))
    for m in _NUM_RE.finditer(claim.text):
        if m.group(0) not in allowed_raw and _canon(m.group(0)) not in allowed_canon:
            return False, f"numeral {m.group(0)!r} not in this claim's cited chunk(s)"
    return True, "ok"


def apply_number_gate(claims: list[Claim], text_by_id: dict[str, str]):
    kept, reasons = [], []
    for claim in claims:
        ok, reason = claim_passes_number_gate(claim, text_by_id)
        (kept if ok else reasons).append(claim if ok else f"{reason}: {claim.text[:80]}")
    return kept, len(claims) - len(kept), reasons
