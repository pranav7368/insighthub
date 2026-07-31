"""Unified, tenant-scoped ingestion.

One uploaded file -> one `datasets` row, scoped to a workspace. Structured
files (csv/xlsx) become a physical raw table (for the dashboard engine)
whose columns are auto-classified; documents (pdf/docx/txt/md) become
citable chunks (for the Q&A engine). The physical table name embeds the
workspace_id so two tenants uploading same-named files never collide, and
all column identifiers are sanitized before they touch SQL.
"""

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from ..analytics.detect import ColumnProfile, detect_schema
from ..core import config, db
from ..core.security import new_id
from ..core.sqlsafe import quote_identifier, safe_table_name, sanitize_identifier
from .chunking import chunk_text
from .parsers import parse_document

STRUCTURED_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


@dataclass
class IngestResult:
    dataset_id: str
    name: str
    kind: str
    row_count: int = 0
    char_count: int = 0
    chunks: int = 0
    columns: list[ColumnProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ws_slug(workspace_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", workspace_id)[:16] or "ws"


def _read_structured(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(io.BytesIO(content))
    return pd.read_excel(io.BytesIO(content))


def _dedupe_columns(names: list[str]) -> list[str]:
    seen, out = {}, []
    for name in names:
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            out.append(name)
    return out


def create_structured_dataset(con, workspace_id: str, name: str, df, source_file: str) -> IngestResult:
    """Turn a ready DataFrame into a first-class structured dataset (physical
    table + detected columns + initial batch). Shared by file upload and by
    materialized joins, so a joined result is a normal dataset the whole engine
    already understands."""
    if df.empty:
        raise ValueError("no data rows")

    df.columns = _dedupe_columns([sanitize_identifier(c) for c in df.columns])
    profiles = detect_schema(df)

    dataset_id = new_id("ds")
    table_name = f"t_{_ws_slug(workspace_id)}_{hashlib.sha1(dataset_id.encode()).hexdigest()[:12]}"
    tq = safe_table_name(table_name)  # system-generated; validate+quote defensively anyway
    batch_id = new_id("batch")
    con.register("_incoming_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {tq} AS SELECT * FROM _incoming_df")
    con.unregister("_incoming_df")
    # provenance column: which append batch each row came from (initial load here)
    con.execute(f'ALTER TABLE {tq} ADD COLUMN {quote_identifier(db.BATCH_COL)} VARCHAR')
    con.execute(f'UPDATE {tq} SET {quote_identifier(db.BATCH_COL)} = ?', [batch_id])

    con.execute(
        """INSERT INTO datasets
           (dataset_id, workspace_id, name, source_file, kind, table_name, row_count, char_count)
           VALUES (?, ?, ?, ?, 'structured', ?, ?, 0)""",
        [dataset_id, workspace_id, name, source_file, table_name, len(df)],
    )
    con.executemany(
        """INSERT INTO dataset_columns
           (dataset_id, workspace_id, column_name, role, subtype, distinct_count, overridden)
           VALUES (?, ?, ?, ?, ?, ?, false)""",
        [(dataset_id, workspace_id, p.name, p.role, p.subtype, p.distinct_count) for p in profiles],
    )
    con.execute(
        """INSERT INTO ingest_batches
           (batch_id, dataset_id, workspace_id, source_file, mode, rows_added)
           VALUES (?, ?, ?, ?, 'initial', ?)""",
        [batch_id, dataset_id, workspace_id, source_file, len(df)],
    )
    return IngestResult(dataset_id, name, "structured", row_count=len(df), columns=profiles)


def ingest_structured(con, workspace_id: str, filename: str, content: bytes, name: str | None) -> IngestResult:
    df = _read_structured(filename, content)
    if df.empty:
        raise ValueError("file has no data rows")
    return create_structured_dataset(con, workspace_id, name or Path(filename).stem, df, filename)


def ingest_document(con, workspace_id: str, filename: str, content: bytes, name: str | None) -> IngestResult:
    units, meta = parse_document(filename, content)
    warnings = []
    if meta.get("skipped_pages"):
        warnings.append(
            f"{len(meta['skipped_pages'])} scanned page(s) with no text layer were skipped "
            "(OCR is a later feature)"
        )
    char_count = sum(len(t) for _, t in units)
    dataset_name = name or Path(filename).stem
    dataset_id = new_id("ds")

    rows, position = [], 0
    for locator, text in units:
        for piece in chunk_text(text):
            position += 1
            rows.append((f"{dataset_id}_c{position:05d}", workspace_id, dataset_id, position, locator, piece))

    if not rows:
        con.execute(
            """INSERT INTO datasets
               (dataset_id, workspace_id, name, source_file, kind, table_name, row_count, char_count)
               VALUES (?, ?, ?, ?, 'document', NULL, 0, 0)""",
            [dataset_id, workspace_id, dataset_name, filename],
        )
        warnings.append("no extractable text; document stored empty")
        return IngestResult(dataset_id, dataset_name, "document", warnings=warnings)

    con.executemany(
        "INSERT INTO chunks (chunk_id, workspace_id, dataset_id, position, locator, text) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.execute(
        """INSERT INTO datasets
           (dataset_id, workspace_id, name, source_file, kind, table_name, row_count, char_count)
           VALUES (?, ?, ?, ?, 'document', NULL, 0, ?)""",
        [dataset_id, workspace_id, dataset_name, filename, char_count],
    )
    return IngestResult(dataset_id, dataset_name, "document", char_count=char_count, chunks=len(rows), warnings=warnings)


def ingest_upload(con, workspace_id: str, filename: str, content: bytes, name: str | None = None) -> IngestResult:
    suffix = Path(filename).suffix.lower()
    if suffix in STRUCTURED_SUFFIXES:
        return ingest_structured(con, workspace_id, filename, content, name)
    if suffix in DOCUMENT_SUFFIXES:
        return ingest_document(con, workspace_id, filename, content, name)
    raise ValueError(f"unsupported file type {suffix!r}")
