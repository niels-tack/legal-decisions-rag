"""SQLite schema shared by the index builder and the query service.

The database is a single portable ``cases.db`` file: ``cases`` holds
per-ruling metadata (including which judicial body - ``source`` - issued
it), ``chunks`` holds one row per numbered-paragraph passage (see
``src.indexing.build_index`` for how paragraph boundaries are found), and
``chunks_fts`` is an FTS5 (BM25) index over ``chunks`` in external-content
mode, so passage text is stored exactly once (in ``chunks``) rather than
duplicated into the FTS5 index. ``embeddings`` is reserved now (keyed by
``chunk_id``) for Phase 2's vector similarity search, but is left empty by
the Phase 1 build - see ``src.indexing.build_index.build_index`` (BM25 only)
vs ``add_embeddings`` (the additive Phase 2 step).

Per the technical requirements' range-request tuning, ``PAGE_SIZE`` must be
set on a connection before any table is created - SQLite only honors
``PRAGMA page_size`` on an empty database.
"""

from __future__ import annotations

import json
import sqlite3

# The documented sweet spot for HTTP range-request (byte-serving) access in
# Phase 1's client-side SQLite-over-HTTP setup: small enough that a query
# touches few bytes per page, at the cost of a larger page count overall.
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

# External-content mode: chunks_fts.rowid is chunks.chunk_id, and the
# indexed 'text' column's actual value lives only in chunks.text - FTS5
# looks it up there (via content_rowid) whenever a query needs it (e.g. for
# a snippet), rather than storing its own second copy.
CHUNKS_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content = 'chunks',
    content_rowid = 'chunk_id',
    tokenize = 'unicode61'
);
"""

# Phase 2 adds vector similarity search over these same chunks. The table
# (and its column names/types) are reserved now, per the technical
# requirements, so the schema doesn't need to change shape later - it is
# simply left unpopulated by the Phase 1 build.
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
    """Create all tables for the shared cases.db schema.

    Must be called on an otherwise-empty connection: this sets
    ``PRAGMA page_size`` first, which SQLite only applies if no tables have
    been created yet on that connection.

    Args:
        conn: An open connection to the target (empty) SQLite database.
    """
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
    """Insert one passage into ``chunks`` and its FTS5 index entry.

    Args:
        conn: An open connection to the target SQLite database.
        chunk_id: The shared id also used as ``chunks_fts.rowid`` and, in
            Phase 2, as the ``embeddings`` table's key.
        case_id: Foreign key into the ``cases`` table.
        section: One of the structural section labels in ``src.schemas``.
        chunk_order: Zero-based position of this chunk within its case,
            preserving document order for later reconstruction/rendering.
        text: The passage's plain text content.
        paragraph_number: This chunk's own numbered identifier (e.g.
            ``"B.7.3"``), or ``None`` for a whole-section fallback chunk
            from a section/body with no paragraph numbering.
        parent_numbers: Ancestor identifiers (e.g. ``["B", "B.7"]`` for
            ``"B.7.3"``), or ``None``/empty when there's nothing to derive
            ancestors from.
    """
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
