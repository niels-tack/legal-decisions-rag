"""SQLite schema shared by the index builder and the query service.

The database is a single portable ``cases.db`` file:
- ``cases``: per-ruling metadata (incl. judicial body).
- ``chunks``: per-paragraph passage data with section label and numbering.
- ``chunks_fts``: FTS5 (BM25) virtual table over ``chunks`` (Phase 1).
- ``embeddings``: dense vector storage for semantic search (Phase 2 additive).
- ``model_meta``: single-row table recording the embedding model configuration
  used when the ``embeddings`` table was populated. A model swap (different
  name, dim, or prefixes) must trigger a full re-embed; storing the config
  here makes that comparison automatic.
"""

from __future__ import annotations

import sqlite3

PAGE_SIZE = 1024

# ---------------------------------------------------------------------------
# Embedding model configuration
# ---------------------------------------------------------------------------

# multilingual-e5-small: MIT-licensed, ~118 MB int8 ONNX, 384-dim, proven on
# Dutch. Challenger: EmbeddingGemma-300M (MRL, on-device design). See
# context/Technical requirements.md for the model selection rationale.
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384

# e5-class models require exact prefix strings prepended to every text before
# encoding. Omitting them silently degrades retrieval quality. Both the
# index-build embedding path (passage prefix) and the query-service embedding
# path (query prefix) import these constants so the requirement is enforced in
# one place and tested explicitly.
EMBEDDING_QUERY_PREFIX = "query: "
EMBEDDING_PASSAGE_PREFIX = "passage: "

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

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

# Single-row table (enforced by CHECK (id = 1)) storing the embedding model
# configuration active when the embeddings table was last populated. The
# query service can read this to verify the bundled ONNX model matches the
# stored vectors. weights_sha256 is nullable; it is populated when the build
# step can compute a hash of the downloaded weights file.
MODEL_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    model_name TEXT NOT NULL,
    vector_dim INTEGER NOT NULL,
    query_prefix TEXT NOT NULL DEFAULT '',
    passage_prefix TEXT NOT NULL DEFAULT '',
    weights_sha256 TEXT
);
"""


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create all tables for the shared cases.db schema.

    Args:
        conn: An open SQLite connection to the target database file.
    """
    conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")
    conn.execute(CASES_TABLE_SQL)
    conn.execute(CHUNKS_TABLE_SQL)
    conn.execute(CHUNKS_FTS_SQL)
    conn.execute(EMBEDDINGS_TABLE_SQL)
    conn.execute(MODEL_META_TABLE_SQL)
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
        conn: An open connection to the destination database.
        chunk_id: The row id to assign (shared between ``chunks`` and
            ``chunks_fts``).
        case_id: Foreign key into the ``cases`` table.
        section: Section label string, e.g. ``"reasoning"`` for GHCC.
        chunk_order: 0-based position within the case (for stable ordering).
        text: The chunk's plain text content.
        paragraph_number: This chunk's own numbered identifier, e.g.
            ``"B.7.3"``. ``None`` for whole-section fallback chunks.
        parent_numbers: Ancestor identifiers, e.g. ``["B", "B.7"]`` for
            ``"B.7.3"``. Defaults to an empty list.
    """
    import json

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


def upsert_model_meta(
    conn: sqlite3.Connection,
    model_name: str,
    vector_dim: int,
    query_prefix: str,
    passage_prefix: str,
    weights_sha256: str | None = None,
) -> None:
    """Write (or overwrite) the single ``model_meta`` row.

    Called by the Phase 2 ``add_embeddings`` step after all vectors have been
    stored. A re-embed after a model change will overwrite the previous record,
    which is the desired behaviour: the table always reflects the currently
    stored vectors, not any historical model.

    Args:
        conn: An open connection to the destination database.
        model_name: HuggingFace model identifier, e.g.
            ``"intfloat/multilingual-e5-small"``.
        vector_dim: Number of dimensions in each stored embedding vector.
        query_prefix: String prepended to every query at retrieval time.
        passage_prefix: String prepended to every passage at index time.
        weights_sha256: SHA-256 hex digest of the model weights file, or
            ``None`` if not computed.
    """
    conn.execute(
        "INSERT OR REPLACE INTO model_meta "
        "(id, model_name, vector_dim, query_prefix, passage_prefix, weights_sha256) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (model_name, vector_dim, query_prefix, passage_prefix, weights_sha256),
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
