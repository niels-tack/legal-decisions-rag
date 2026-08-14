"""SQLite schema shared by the index builder and the query service.

The database is a single portable ``cases.db`` file: 
- ``cases``: per-ruling metadata (incl. judicial body)
- ``chunks``: per-paragraph passage data
- ``chunks_fts``: FTS5 (BM25) index over ``chunks`` .
- ``embeddings``: embeddings vector similarity search (TO DO PHASE 2)
"""

from __future__ import annotations

import json
import sqlite3

PAGE_SIZE = 1024

CASES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    case_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    ecli TEXT NOT NULL UNIQUE,
    arrest_number TEXT NOT NULL,
    role_number TEXT NOT NULL,
    file_slug TEXT NOT NULL UNIQUE,
    ruling_date TEXT NOT NULL,
    language TEXT NOT NULL,
    procedure_type TEXT NOT NULL,
    controlled_norm TEXT NOT NULL,
    outcome TEXT NOT NULL,
    keywords TEXT NOT NULL,
    source_pdf_url TEXT NOT NULL,
    title TEXT NOT NULL
);
"""

CHUNKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL,
    section TEXT NOT NULL,
    paragraph_number TEXT,
    parent_numbers TEXT NOT NULL,
    chunk_order INTEGER NOT NULL,
    text TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases (case_id)
);
"""

CHUNKS_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content = 'chunks',
    content_rowid = 'chunk_id',
    tokenize = 'unicode61'
);
"""

EMBEDDINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    vector BLOB NOT NULL,
    FOREIGN KEY (chunk_id) REFERENCES chunks (chunk_id)
);
"""

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create all tables for the shared cases.db schema."""
    conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")
    conn.execute(CASES_TABLE_SQL)
    conn.execute(CHUNKS_TABLE_SQL)
    conn.execute(CHUNKS_FTS_SQL)
    conn.execute(EMBEDDINGS_TABLE_SQL)
    conn.commit()


def insert_chunk(
    conn: sqlite3.Connection,
    chunk_id: int,
    case_id: int,
    section: str,
    chunk_order: int,
    text: str,
    paragraph_number: str | None = None,
    parent_numbers: list[str] | None = None,
) -> None:
    """Insert one passage into ``chunks`` and its FTS5 index entry."""
    conn.execute(
        "INSERT INTO chunks "
        "(chunk_id, case_id, section, paragraph_number, parent_numbers, "
        "chunk_order, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            chunk_id,
            case_id,
            section,
            paragraph_number,
            json.dumps(parent_numbers or []),
            chunk_order,
            text,
        ),
    )
    conn.execute(
        "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
        (chunk_id, text),
    )


def tune_for_range_access(conn: sqlite3.Connection) -> None:
    """Run the post-build maintenance the range-request VFS relies on.

    ``VACUUM`` rewrites the file so the ``page_size`` set at creation is
    actually reflected on disk, and defragments it; ``ANALYZE`` refreshes
    the query planner statistics FTS5's ``bm25()`` ranking and the
    ``cases`` metadata filters both depend on.

    Args:
        conn: An open connection to the fully populated database.
    """
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
