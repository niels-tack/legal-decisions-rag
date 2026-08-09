"""SQLite schema shared by the index builder and the query service.

The database is a single portable ``cases.db`` file combining a lexical
FTS5 table (BM25) with a plain table of passage embeddings for vector
similarity. ``passage_embeddings.passage_id`` is always assigned as the
explicit ``rowid`` of the matching row in ``passages_fts``, so the two
tables can be joined on that id without a separate foreign-key column.
"""

from __future__ import annotations

import sqlite3

CASES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    case_id INTEGER PRIMARY KEY,
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

PASSAGES_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    case_id UNINDEXED,
    section UNINDEXED,
    text,
    tokenize = 'unicode61'
);
"""

PASSAGE_EMBEDDINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS passage_embeddings (
    passage_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    model_name TEXT NOT NULL,
    vector BLOB NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases (case_id)
);
"""

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create all tables required by the hybrid search index.

    Args:
        conn: An open connection to the target SQLite database.
    """
    conn.execute(CASES_TABLE_SQL)
    conn.execute(PASSAGES_FTS_SQL)
    conn.execute(PASSAGE_EMBEDDINGS_TABLE_SQL)
    conn.commit()


def insert_passage(
    conn: sqlite3.Connection,
    passage_id: int,
    case_id: int,
    section: str,
    text: str,
) -> None:
    """Insert one passage into ``passages_fts`` using an explicit rowid.

    The explicit rowid keeps ``passages_fts.rowid`` equal to
    ``passage_embeddings.passage_id`` so the two tables can be joined.

    Args:
        conn: An open connection to the target SQLite database.
        passage_id: The shared id also used as the embeddings table's key.
        case_id: Foreign key into the ``cases`` table.
        section: One of the structural section labels in ``src.schemas``.
        text: The passage's plain text content.
    """
    conn.execute(
        "INSERT INTO passages_fts (rowid, case_id, section, text) VALUES (?, ?, ?, ?)",
        (passage_id, case_id, section, text),
    )
