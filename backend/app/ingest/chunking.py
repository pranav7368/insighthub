"""Split extracted document text into overlapping, citable chunks.

Paragraph-aware: never splits mid-paragraph unless a single paragraph
exceeds the window, then falls back to a sliding character window. Overlap
keeps a fact from being cut exactly at a boundary and losing citability.
"""

import re

from ..core import config


def split_into_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]


def chunk_text(text, chunk_chars=None, overlap=None, min_chars=None) -> list[str]:
    chunk_chars = chunk_chars or config.CHUNK_CHARS
    overlap = overlap if overlap is not None else config.CHUNK_OVERLAP
    min_chars = min_chars if min_chars is not None else config.MIN_CHUNK_CHARS

    paragraphs = split_into_paragraphs(text)
    if not paragraphs:
        return []
    chunks, current, current_len = [], [], 0

    def flush():
        if current:
            joined = "\n\n".join(current).strip()
            if len(joined) >= min_chars:
                chunks.append(joined)

    for para in paragraphs:
        if len(para) > chunk_chars:
            flush()
            current, current_len = [], 0
            for start in range(0, len(para), chunk_chars - overlap):
                piece = para[start : start + chunk_chars]
                if len(piece) >= min_chars:
                    chunks.append(piece)
            continue
        if current_len + len(para) > chunk_chars and current:
            flush()
            tail = ("\n\n".join(current))[-overlap:] if overlap else ""
            current = [tail] if tail else []
            current_len = len(tail)
        current.append(para)
        current_len += len(para)
    flush()
    return chunks
