"""#4 AI narrative + suggested actions (provider-agnostic).

The LLM's job here is to PHRASE, not to compute. It is handed a compact set
of FACTS already computed by the deterministic engine (KPIs, growth,
insights, pareto) - never the raw rows - and asked for an executive narrative
and prioritized recommendations. A number gate then checks that every figure
in the generated text actually appears in the supplied facts; any that don't
are reported in `unverified_numbers`, so a hallucinated number is surfaced,
never silently trusted. Works with Claude, OpenAI, Gemini, Ollama, etc., or
the offline deterministic fallback.
"""

import json
import re
from string import Template

from ..core import config
from ..qa.llm import LLM, extract_json, get_llm, provider_status

_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def build_facts(dashboard: dict) -> dict:
    """A compact, grounded snapshot of the dashboard for the LLM."""
    kpis = [
        {"name": k["column"], "subtype": k["subtype"], "total": k["total"],
         "mom_change_pct": k["delta_pct"]}
        for k in dashboard.get("kpis", [])
    ]
    facts = {
        "dataset": dashboard.get("dataset", {}).get("name"),
        "rows": dashboard.get("row_count_filtered"),
        "kpis": kpis,
        "growth": dashboard.get("growth"),
        "insights": [{"title": i["title"], "detail": i["detail"], "category": i.get("category")}
                     for i in dashboard.get("insights", [])],
    }
    if dashboard.get("pareto"):
        p = dashboard["pareto"]
        facts["pareto"] = {"dimension": p.get("dimension"), "measure": p.get("measure"),
                           "top_n_for_80pct": p.get("n_for_80"), "total_categories": p.get("total_categories")}
    corr = dashboard.get("correlations")
    if corr and corr.get("strongest"):
        facts["strongest_correlation"] = corr["strongest"]
    return facts


def _canon(value: str) -> str:
    cleaned = value.replace(",", "").rstrip("%")
    try:
        return f"{float(cleaned):g}"
    except ValueError:
        return cleaned


def _allowed_numbers(facts: dict) -> set[str]:
    # ensure_ascii=False keeps '₹' as itself; escaping it to ₹ would let
    # the trailing '9' merge with the next digit and corrupt tokenization.
    text = json.dumps(facts, ensure_ascii=False)
    allowed = set()
    for m in _NUM_RE.finditer(text):
        allowed.add(m.group(0))
        allowed.add(_canon(m.group(0)))
    return allowed


def _unverified_numbers(text: str, allowed: set[str]) -> list[str]:
    bad = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0)
        if raw not in allowed and _canon(raw) not in allowed:
            bad.append(raw)
    return sorted(set(bad))


def _validate(parsed: dict, facts: dict) -> dict:
    headline = str(parsed.get("headline", "")).strip()
    narrative = str(parsed.get("narrative", "")).strip()
    recs = []
    for r in parsed.get("recommendations", []) or []:
        if not isinstance(r, dict) or not str(r.get("title", "")).strip():
            continue
        priority = r.get("priority") if r.get("priority") in ("high", "medium", "low") else "medium"
        recs.append({"title": str(r["title"]).strip(),
                     "detail": str(r.get("detail", "")).strip(), "priority": priority})

    allowed = _allowed_numbers(facts)
    joined = " ".join([headline, narrative] + [f"{r['title']} {r['detail']}" for r in recs])
    unverified = _unverified_numbers(joined, allowed)

    status = provider_status()
    return {
        "headline": headline, "narrative": narrative, "recommendations": recs,
        "unverified_numbers": unverified,
        "provider": status["provider"], "model": status["model"],
    }


def generate_narrative(con, workspace_id: str, dataset_id: str, llm: LLM | None = None) -> dict:
    from .engine import compute_dashboard

    dashboard = compute_dashboard(con, workspace_id, dataset_id)
    facts = build_facts(dashboard)
    llm = llm or get_llm()
    prompt = Template(config.prompt("narrative")).substitute(
        facts_json=json.dumps(facts, indent=1, ensure_ascii=False))
    try:
        parsed = extract_json(llm.complete(prompt, max_tokens=1500))
    except Exception as exc:
        return {"headline": "", "narrative": f"Could not generate narrative ({exc}).",
                "recommendations": [], "unverified_numbers": [],
                "provider": provider_status()["provider"], "model": provider_status()["model"]}
    return _validate(parsed, facts)
