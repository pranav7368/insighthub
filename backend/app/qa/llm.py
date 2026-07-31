"""LLM + embedder access, provider-agnostic, with deterministic offline
stand-ins.

Every stage takes an object satisfying the LLM protocol, so the whole app is
independent of WHICH provider is used. get_llm() resolves the provider from
config: Claude, OpenAI, Gemini, Ollama (local), Groq, OpenRouter, Together,
any OpenAI-compatible endpoint, or the offline rule-based stand-in. Tests
inject fakes and never hit the network. The LLM never computes numbers; code
gates validate its output.
"""

import hashlib
import json
import os
import re
from typing import Protocol, Sequence

import numpy as np

from ..core import config

# Default model per provider (overridable with IH_MODEL). Kept current per the
# provider docs; users can point IH_MODEL at any model the provider offers.
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "ollama": "llama3.1",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "openai/gpt-4o-mini",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
}

# base_url + the env var that conventionally holds each provider's key. Ollama
# is local and needs no key. All are reachable through the OpenAI-compatible
# client, so one adapter covers them all.
_OPENAI_COMPATIBLE = {
    "openai": (None, "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
}


# --------------------------------------------------------------- LLM -----

class LLM(Protocol):
    def complete(self, prompt: str, system: str = "", temperature: float | None = None,
                 max_tokens: int = 4096) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or config.MODEL or _DEFAULT_MODELS["anthropic"]

    def complete(self, prompt, system="", temperature=None, max_tokens=4096):
        kwargs = dict(model=self.model, max_tokens=max_tokens,
                      messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self.client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if b.type == "text")


class OpenAICompatibleLLM:
    """One adapter for every OpenAI-compatible provider (OpenAI, Gemini,
    Ollama, Groq, OpenRouter, Together, or a custom base_url)."""

    def __init__(self, provider: str):
        from openai import OpenAI

        base_default, key_env = _OPENAI_COMPATIBLE.get(provider, (None, None))
        base_url = config.LLM_BASE_URL or base_default
        api_key = config.LLM_API_KEY or (os.environ.get(key_env) if key_env else None) or "not-needed"
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = config.MODEL or _DEFAULT_MODELS.get(provider, "gpt-4o-mini")

    def complete(self, prompt, system="", temperature=None, max_tokens=4096):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs = dict(model=self.model, messages=messages, max_tokens=max_tokens)
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def resolve_provider() -> str:
    """Which provider is active, without constructing a client or exposing
    any secret. 'offline' means no external LLM is used."""
    if config.OFFLINE:
        return "offline"
    provider = config.LLM_PROVIDER
    if provider:
        return provider
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "offline"


def provider_status() -> dict:
    provider = resolve_provider()
    if provider in ("offline", "anthropic"):
        model = None if provider == "offline" else (config.MODEL or _DEFAULT_MODELS["anthropic"])
    else:
        model = config.MODEL or _DEFAULT_MODELS.get(provider)
    return {"provider": provider, "model": model}


def get_llm() -> LLM:
    provider = resolve_provider()
    if provider == "offline":
        return OfflineLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider in _OPENAI_COMPATIBLE or provider == "openai-compatible":
        return OpenAICompatibleLLM(provider)
    raise ValueError(f"unknown IH_LLM_PROVIDER {provider!r}")


def extract_json(text: str):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"no JSON found in LLM response: {text[:200]!r}")


# --------------------------------------------------------- Embedder ------

class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(self.MODEL_NAME)

    def encode(self, texts):
        vecs = self.model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float64)


class HashingEmbedder:
    """Deterministic char-trigram hashing embedder; offline/test fallback."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _grams(self, text):
        text = "".join(c.lower() if c.isalnum() else " " for c in text)
        grams = []
        for word in text.split():
            padded = f"#{word}#"
            grams.extend(padded[i : i + 3] for i in range(len(padded) - 2))
        return grams

    def encode(self, texts):
        m = np.zeros((len(texts), self.dim))
        for row, text in enumerate(texts):
            for gram in self._grams(text):
                d = hashlib.md5(gram.encode()).digest()
                idx = int.from_bytes(d[:4], "little") % self.dim
                m[row, idx] += 1.0 if d[4] % 2 == 0 else -1.0
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return m / norms


def get_embedder() -> Embedder:
    if config.OFFLINE:
        return HashingEmbedder()
    try:
        return SentenceTransformerEmbedder()
    except Exception as exc:
        print(f"[ih] sentence-transformers unavailable ({exc!r}); using HashingEmbedder")
        return HashingEmbedder()


# --------------------------------------------- Offline LLM stand-in ------

_STOP = {"the", "a", "an", "and", "is", "it", "to", "of", "in", "for", "this", "was",
         "with", "my", "not", "on", "but", "very", "after", "i", "we", "what", "how",
         "does", "do", "did", "when", "where", "who", "which", "are", "has", "have",
         "from", "at", "so", "be", "there", "that"}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOP}


def _offline_compose(payload: dict) -> dict:
    question = payload.get("question", "")
    chunks = payload.get("chunks", [])
    q = _stems(question)
    scored = sorted(
        ((len(q & _stems(c["text"])), c) for c in chunks if q & _stems(c["text"])),
        key=lambda p: -p[0],
    )
    if not scored:
        return {"claims": [], "confidence": "low", "abstained": True,
                "abstention_reason": "no ingested chunk overlaps with the question's keywords"}
    claims = []
    for _, c in scored[:3]:
        snippet = c["text"].strip()
        if len(snippet) > 220:
            snippet = snippet[:220].rsplit(" ", 1)[0] + "..."
        claims.append({
            "text": f'According to {c.get("title") or "the document"} ({c.get("locator") or "?"}): "{snippet}"',
            "evidence": [c["chunk_id"]], "type": "quote",
        })
    return {"claims": claims, "confidence": "medium", "abstained": False}


def _offline_verify(payload: dict) -> dict:
    verdicts = []
    for claim in payload.get("claims", []):
        ok = any(e.get("content") for e in claim.get("evidence", []))
        verdicts.append({"index": claim["index"], "verdict": "SUPPORTED" if ok else "UNSUPPORTED",
                         "reason": "offline: evidence present" if ok else "no evidence content"})
    return {"verdicts": verdicts}


def _offline_narrative(facts: dict) -> dict:
    """Deterministic executive brief built from the pre-computed insights /
    facts - so #4 works with no external LLM. A real provider produces richer
    prose; this only stitches the facts together."""
    insights = facts.get("insights", [])
    headline = insights[0]["title"] if insights else f"Summary of {facts.get('dataset', 'your data')}"
    narrative = " ".join(i["detail"] for i in insights[:3]) or "No notable patterns were detected in the current view."

    recs, seen = [], set()
    for i in insights:
        cat, title = i.get("category"), i["title"]
        rule = {
            "concentration": ("Reduce concentration risk", "Diversify so the business depends less on the single dominant segment.", "high"),
            "anomaly": ("Investigate the anomaly", f"Look into the cause behind: {i['detail']}", "high"),
            "trend": ("Act on the trend", "Reinforce what is working if rising, or address the drivers if falling.", "medium"),
            "margin": ("Protect margin", "Review pricing and cost drivers to defend or improve the margin.", "medium"),
            "pareto": ("Focus on the vital few", "Concentrate effort on the top segments that drive most of the total.", "medium"),
            "leader": ("Double down on the leader", "Study why the top segment leads and replicate it elsewhere.", "low"),
        }.get(cat)
        if rule and cat not in seen:
            seen.add(cat)
            recs.append({"title": rule[0], "detail": rule[1], "priority": rule[2]})
    if not recs:
        recs.append({"title": "Collect more data", "detail": "Add more history so trends and forecasts become reliable.", "priority": "low"})
    return {"headline": headline, "narrative": narrative, "recommendations": recs[:5]}


def _offline_nl_query(payload: dict) -> dict:
    """Deterministic keyword parser: natural-language question -> query
    intent, using the same field vocabulary the online model gets. Good
    enough to demo/test the conversational path without an API key."""
    import re as _re

    q = (payload.get("question") or "").lower()
    schema = payload.get("schema") or {}
    measures = [m["name"] for m in schema.get("measures", [])]
    dims = schema.get("dimensions", [])
    dim_names = [d["name"] for d in dims]
    date_col = schema.get("date_column")

    def tokens(name):
        return [t for t in _re.split(r"[^a-z0-9]+", name.lower()) if len(t) >= 3]

    # metric: measure whose name-tokens appear in the question
    metric = next((m for m in measures if any(t in q for t in tokens(m))), None)
    if metric is None:
        if "sales" in q or "revenue" in q:
            metric = next((m for m in measures if "revenue" in m.lower() or "sales" in m.lower()), None)

    # Words that mean "count the rows" rather than "aggregate a column".
    _ROW_WORDS = ("record", "records", "row", "rows", "entry", "entries", "transaction",
                  "transactions", "order", "orders", "line items")
    asks_for_rows = any(w in q for w in _ROW_WORDS)

    # Everything the schema knows about, as words.
    vocabulary = set()
    for name in measures + dim_names:
        vocabulary.update(tokens(name))
    for d in dims:
        for v in d.get("example_values", []):
            vocabulary.update(tokens(str(v)))

    # (1) An unresolved ENTITY: "revenue for Antarctica" when no such region
    # exists. The reliable signal is a capitalised word mid-sentence — people
    # capitalise names, not verbs. A lowercase content-word scan cannot tell
    # "Antarctica" from "sold" and refuses ordinary English.
    original = payload.get("question") or ""
    proper_nouns = _re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][A-Za-z]{2,})\b", original)
    unresolved = [
        w for w in proper_nouns
        if not any(t in vocabulary for t in tokens(w))
    ]

    # (2) An unresolved MEASURE: "total profit margin" with no profit column.
    # Only consulted when nothing matched, so ordinary phrasing is unaffected.
    if metric is None and not asks_for_rows:
        _STOPWORDS = {
            "the", "what", "which", "who", "how", "much", "many", "and", "for", "from",
            "with", "was", "were", "are", "is", "did", "does", "our", "all", "show",
            "give", "tell", "get", "total", "sum", "average", "avg", "mean", "count",
            "number", "highest", "lowest", "best", "worst", "top", "bottom", "over",
            "per", "each", "there", "this", "that", "have", "has", "had", "into",
            "value", "values", "data", "dataset", "amount", "please", "across",
            "sold", "came", "made", "spent", "earned", "generated", "achieved",
            # time language: handled by date filters, never a measure
            "time", "month", "months", "monthly", "year", "years", "yearly", "week",
            "weeks", "weekly", "daily", "trend", "quarter", "quarters", "last", "first",
            "recent", "period", "date", "dates", "today", "yesterday", "ytd", "mtd",
        } | set(_ROW_WORDS)
        candidates = [
            t for t in _re.split(r"[^a-z0-9]+", q)
            if len(t) >= 4 and t not in _STOPWORDS and t not in vocabulary
        ]
        if candidates:
            # hand it to the validator, which refuses naming what IS available
            metric = candidates[0]

    if metric is None and measures and not asks_for_rows:
        metric = measures[0]

    # aggregation
    if any(w in q for w in ("average", "avg", "mean")):
        agg = "avg"
    elif asks_for_rows and any(w in q for w in ("how many", "number of", "count")):
        # "how many orders" counts rows; "how many units" sums the units column
        agg = "count"
    elif metric is None and any(w in q for w in ("how many", "number of", "count")):
        agg = "count"
    elif any(w in q for w in ("minimum", "min ")):
        agg = "min"
    elif any(w in q for w in ("maximum ", "max ")):
        agg = "max"
    else:
        agg = "sum"

    # group_by
    group_by = None
    if any(w in q for w in ("over time", "trend", "monthly", "by month", "over the months", "each month")):
        group_by = "__month__" if date_col else None
    if group_by is None:
        group_by = next((d for d in dim_names if any(t in q for t in tokens(d))), None)

    # filters: any known dimension value mentioned
    filters = {}
    for d in dims:
        for v in d.get("example_values", []):
            if v is not None and str(v).lower() in q and len(str(v)) >= 2:
                filters[d["name"]] = v
                break

    # sort / limit
    sort = "asc" if any(w in q for w in ("lowest", "least", "bottom", "smallest", "worst")) else "desc"
    m = _re.search(r"top\s+(\d+)", q)
    limit = int(m.group(1)) if m else None

    # chart type
    if group_by == "__month__":
        chart = "line"
    elif group_by:
        chart = "pie" if any(w in q for w in ("share", "contribution", "proportion", "split", "breakdown")) else "bar"
    else:
        chart = "kpi"

    # words the question used that the dataset knows nothing about; the
    # validator turns these into a refusal rather than a confident number
    unresolved = [t for t in unresolved if t not in {str(v).lower() for v in filters.values()}]

    return {"metric": metric, "aggregation": agg, "group_by": group_by,
            "filters": filters, "sort": sort, "limit": limit, "chart_type": chart,
            "unresolved": unresolved}


class OfflineLLM:
    def complete(self, prompt, system="", temperature=None, max_tokens=4096):
        role = (re.search(r"^# ROLE:\s*(\w+)", prompt, re.MULTILINE) or [None, "unknown"])[1]
        block = re.search(r"<INPUT>\s*(.*?)\s*</INPUT>", prompt, re.DOTALL)
        data = json.loads(block.group(1)) if block else {}
        if role == "composer":
            return json.dumps(_offline_compose(data))
        if role == "verifier":
            return json.dumps(_offline_verify(data))
        if role == "nl_query":
            return json.dumps(_offline_nl_query(data))
        if role == "narrative":
            return json.dumps(_offline_narrative(data))
        raise ValueError(f"OfflineLLM: unknown role {role!r}")
