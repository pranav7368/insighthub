"""Grounded Q&A over a workspace's document chunks.

Retrieval is hybrid (BM25 via python + embedding cosine) and ALWAYS scoped
to the caller's workspace_id. Small corpora skip retrieval (CAG: pass all
chunks); large corpora retrieve top-k (RAG). Then Gates 2-4 run:
  GATE 2 schema/citation, GATE 3 numbers-in-cited-chunk, GATE 4 adversarial
  verifier. Nothing survives without a citation; if nothing survives, the
  system abstains and still lists what little evidence exists.
"""

import json
import math
import re
from collections import Counter
from string import Template

from ..core import config
from .gates import Answer, Claim, apply_number_gate, validate_claims_schema
from .llm import Embedder, LLM, extract_json, get_embedder, get_llm

_TOK = re.compile(r"[a-z0-9']+")


def _tokens(text):
    return _TOK.findall(text.lower())


def _corpus_chars(con, workspace_id):
    return con.execute(
        "SELECT coalesce(sum(length(text)), 0) FROM chunks WHERE workspace_id = ?", [workspace_id]
    ).fetchone()[0]


def _all_chunks(con, workspace_id):
    rows = con.execute(
        """SELECT c.chunk_id, d.name, c.locator, c.text
           FROM chunks c JOIN datasets d USING (dataset_id)
           WHERE c.workspace_id = ? ORDER BY c.dataset_id, c.position""",
        [workspace_id],
    ).fetchall()
    return [{"chunk_id": r[0], "title": r[1], "locator": r[2], "text": r[3]} for r in rows]


def ensure_embeddings(con, workspace_id, embedder: Embedder):
    rows = con.execute(
        """SELECT c.chunk_id, c.text FROM chunks c
           LEFT JOIN chunk_embeddings e USING (chunk_id)
           WHERE c.workspace_id = ? AND e.chunk_id IS NULL""",
        [workspace_id],
    ).fetchall()
    if not rows:
        return 0
    vecs = embedder.encode([t for _, t in rows])
    con.executemany(
        "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, workspace_id, embedding) VALUES (?, ?, ?)",
        [(cid, workspace_id, v.tolist()) for (cid, _), v in zip(rows, vecs)],
    )
    return len(rows)


def _bm25(con, workspace_id, question, k1=1.5, b=0.75):
    docs = con.execute("SELECT chunk_id, text FROM chunks WHERE workspace_id = ?", [workspace_id]).fetchall()
    if not docs:
        return {}
    toks = {cid: _tokens(t) for cid, t in docs}
    avgdl = sum(len(t) for t in toks.values()) / len(toks)
    df = Counter()
    for t in toks.values():
        df.update(set(t))
    n = len(toks)
    query = set(_tokens(question))
    scores = {}
    for cid, t in toks.items():
        tf = Counter(t)
        s = 0.0
        for term in query:
            if term in tf:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(t) / avgdl))
        if s > 0:
            scores[cid] = s
    return scores


def _cosine(con, workspace_id, question, embedder):
    import numpy as np

    rows = con.execute(
        "SELECT chunk_id, embedding FROM chunk_embeddings WHERE workspace_id = ?", [workspace_id]
    ).fetchall()
    if not rows:
        return {}
    m = np.array([r[1] for r in rows])
    q = embedder.encode([question])[0]
    if m.shape[1] != q.shape[0]:
        return {}
    norms = np.linalg.norm(m, axis=1)
    norms[norms == 0] = 1.0
    sims = (m @ q) / (norms * (np.linalg.norm(q) or 1.0))
    return {rows[i][0]: float(sims[i]) for i in range(len(rows))}


def _normalize(scores):
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi == lo:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _retrieve(con, workspace_id, question, embedder, top_k):
    bm, cos = _normalize(_bm25(con, workspace_id, question)), _normalize(_cosine(con, workspace_id, question, embedder))
    combined = {cid: 0.5 * bm.get(cid, 0) + 0.5 * cos.get(cid, 0) for cid in set(bm) | set(cos)}
    ranked = sorted(combined.items(), key=lambda kv: -kv[1])[:top_k]
    out = []
    for cid, _ in ranked:
        row = con.execute(
            """SELECT c.chunk_id, d.name, c.locator, c.text FROM chunks c
               JOIN datasets d USING (dataset_id) WHERE c.chunk_id = ? AND c.workspace_id = ?""",
            [cid, workspace_id],
        ).fetchone()
        if row:
            out.append({"chunk_id": row[0], "title": row[1], "locator": row[2], "text": row[3]})
    return out


def _preview(question, chunks, limit=2):
    q = {w[:5] for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) >= 3}
    ranked = sorted(chunks, key=lambda c: len(q & {w[:5] for w in re.findall(r'[a-z0-9]+', c['text'].lower())}), reverse=True)
    parts = [f'[{c["chunk_id"]}] ({c.get("title")}, {c.get("locator")}): "{c["text"][:150]}..."' for c in ranked[:limit]]
    return "; ".join(parts) if parts else "no related content found"


def answer_question(con, workspace_id, question, llm: LLM = None, embedder: Embedder = None, top_k=None) -> Answer:
    llm = llm or get_llm()
    embedder = embedder or get_embedder()
    top_k = top_k or config.TOP_K

    ensure_embeddings(con, workspace_id, embedder)
    size = _corpus_chars(con, workspace_id)
    mode = "cag" if size <= config.CAG_MAX_CORPUS_CHARS else "rag"
    chunks = _all_chunks(con, workspace_id) if mode == "cag" else _retrieve(con, workspace_id, question, embedder, top_k)

    def abstain(reason, **counts):
        return Answer(question=question, mode=mode, abstained=True, confidence="low",
                      abstention_reason=reason, **counts)

    if not chunks:
        return abstain("no ingested documents relate to this question")

    payload = {"question": question, "chunks": [
        {"chunk_id": c["chunk_id"], "title": c["title"], "locator": c["locator"], "text": c["text"]} for c in chunks]}
    try:
        parsed = extract_json(llm.complete(
            Template(config.prompt("compose_answer")).substitute(payload_json=json.dumps(payload, indent=1)),
            max_tokens=2048))
    except Exception as exc:
        return abstain(f"composer failed ({exc})")

    if isinstance(parsed, dict) and parsed.get("abstained"):
        reason = str(parsed.get("abstention_reason") or "composer abstained")
        return abstain(f"{reason}. What exists: {_preview(question, chunks)}")

    supplied = {c["chunk_id"] for c in chunks}
    # include locator in the number-gate source: prompt cites it and it is
    # code-generated ground truth, not an LLM invention
    text_by_id = {c["chunk_id"]: f'{c["text"]} {c.get("locator") or ""}' for c in chunks}

    claims, removed_schema = validate_claims_schema(parsed, supplied)
    claims, removed_numbers, _ = apply_number_gate(claims, text_by_id)

    removed_verifier = 0
    if claims:
        vpayload = {"question": question, "claims": [
            {"index": i, "text": c.text, "evidence": [{"id": e, "content": text_by_id.get(e, "")} for e in c.evidence]}
            for i, c in enumerate(claims)]}
        try:
            vraw = extract_json(llm.complete(
                Template(config.prompt("verify_answer")).substitute(payload_json=json.dumps(vpayload, indent=1)),
                temperature=0.0, max_tokens=2048))
        except Exception as exc:
            return abstain(f"verifier unavailable ({exc}); refusing to answer unverified",
                           claims_removed_by_schema=removed_schema, claims_removed_by_number_gate=removed_numbers)
        verdicts = {}
        for v in vraw.get("verdicts", []):
            try:
                verdicts[int(v["index"])] = str(v.get("verdict", "")).upper()
            except (KeyError, TypeError, ValueError):
                continue
        surviving = []
        for i, c in enumerate(claims):
            if verdicts.get(i) == "SUPPORTED":
                surviving.append(c)
            else:
                removed_verifier += 1
        claims = surviving

    counts = dict(claims_removed_by_schema=removed_schema, claims_removed_by_number_gate=removed_numbers,
                  claims_removed_by_verifier=removed_verifier)
    if not claims:
        return abstain("no claims survived the validation gates. What exists: " + _preview(question, chunks), **counts)

    conf = parsed.get("confidence") if parsed.get("confidence") in ("low", "medium", "high") else "low"
    if sum(counts.values()) > 0 and conf == "high":
        conf = "medium"
    return Answer(question=question, mode=mode, claims=claims, confidence=conf, abstained=False, **counts)
