"""Per-format text extraction for the document (Q&A) path.

Returns a list of (locator, text) units - text destined for chunking,
tagged with a human-readable locator (page number, paragraph) so citations
stay traceable to a spot in the original file. Structured formats
(csv/xlsx) are handled separately by the analytics path, not here.
"""

import io
from pathlib import Path


def parse_text_bytes(content: bytes):
    text = content.decode("utf-8", errors="replace")
    return [("file", text)], {}


def parse_docx_bytes(content: bytes):
    from docx import Document

    doc = Document(io.BytesIO(content))
    units = []
    for i, para in enumerate((p for p in doc.paragraphs if p.text.strip()), start=1):
        units.append((f"paragraph {i}", para.text.strip()))
    for t_idx, table in enumerate(doc.tables, start=1):
        headers = [c.text.strip() for c in table.rows[0].cells] if table.rows else []
        for r_idx, row in enumerate(table.rows[1:], start=2):
            parts = [f"{h}: {c.text.strip()}" for h, c in zip(headers, row.cells) if c.text.strip()]
            if parts:
                units.append((f"table {t_idx} row {r_idx}", "; ".join(parts)))
    return units, {}


def parse_pdf_bytes(content: bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    units, skipped = [], []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if len(text) < 20:
            skipped.append(i)  # scanned page, no text layer (OCR is a later feature)
            continue
        units.append((f"page {i}", text))
    return units, {"skipped_pages": skipped}


DOC_PARSERS = {
    ".txt": parse_text_bytes,
    ".md": parse_text_bytes,
    ".docx": parse_docx_bytes,
    ".pdf": parse_pdf_bytes,
}


def parse_document(filename: str, content: bytes):
    suffix = Path(filename).suffix.lower()
    parser = DOC_PARSERS.get(suffix)
    if parser is None:
        raise ValueError(f"unsupported document type {suffix!r}")
    return parser(content)
