"""Tests for src.indexing.build_index against small synthetic fixtures.

These tests never load the real sentence-transformers model - that model is
slow to download and irrelevant to the indexing logic under test. Instead
they inject a deterministic, hash-based fake embedding function so the
tests stay fast and hermetic.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from src.indexing.build_index import build_index

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FAKE_EMBEDDING_DIM = 8


def fake_embed_texts(texts: list[str]) -> np.ndarray:
    """Deterministically embed texts via a per-text hash, for fast tests.

    Args:
        texts: Passage texts to "embed".

    Returns:
        A ``(len(texts), FAKE_EMBEDDING_DIM)`` float32 array. Identical
        input text always yields an identical vector, and different texts
        are (with overwhelming probability) mapped to different vectors,
        which is enough to exercise storage/shape assertions without a
        real model.
    """
    vectors = np.zeros((len(texts), FAKE_EMBEDDING_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vectors[row] = np.frombuffer(
            digest[:FAKE_EMBEDDING_DIM], dtype=np.uint8
        ).astype(np.float32)
    return vectors


# Exposed so build_index records this string instead of the real
# EMBEDDING_MODEL_NAME, proving the model-name-reporting hook works.
fake_embed_texts.model_name = "fake-hash-embedder"


@pytest.fixture
def built_db(tmp_path: Path) -> Path:
    """Build a test database from the fixtures directory and return its path."""
    db_path = tmp_path / "cases.db"
    build_index(FIXTURES_DIR, db_path, embed_fn=fake_embed_texts)
    return db_path


def test_valid_cases_are_inserted(built_db: Path) -> None:
    """Only the two well-formed fixtures should produce rows in cases."""
    conn = sqlite3.connect(built_db)
    try:
        rows = conn.execute(
            "SELECT ecli, file_slug, title FROM cases ORDER BY ecli"
        ).fetchall()
    finally:
        conn.close()

    assert [row[0] for row in rows] == [
        "ECLI:BE:GHCC:2025:ARR.001",
        "ECLI:BE:GHCC:2025:ARR.002",
    ]
    assert rows[0][1] == "2025-001n"
    assert rows[0][2] == "Discriminatie op grond van leeftijd bij aanwerving"


def test_broken_frontmatter_is_skipped_not_crashed(built_db: Path) -> None:
    """The fixture missing a required CaseMetadata field must be skipped cleanly."""
    conn = sqlite3.connect(built_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE ecli = ?",
            ("ECLI:BE:GHCC:2025:ARR.003",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 0


def test_fts_match_finds_expected_case(built_db: Path) -> None:
    """A keyword unique to one fixture's facts section should be found via FTS5."""
    conn = sqlite3.connect(built_db)
    try:
        rows = conn.execute(
            "SELECT case_id, section FROM passages_fts WHERE passages_fts MATCH ?",
            ("discriminatie",),
        ).fetchall()
        case_id = conn.execute(
            "SELECT case_id FROM cases WHERE ecli = ?",
            ("ECLI:BE:GHCC:2025:ARR.001",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert rows, "expected at least one FTS hit for 'discriminatie'"
    assert all(row[0] == case_id for row in rows)
    # The word only appears in case 001's facts section.
    assert {row[1] for row in rows} == {"facts"}


def test_fts_match_excludes_unrelated_case(built_db: Path) -> None:
    """A term specific to case 002 should not match case 001's passages."""
    conn = sqlite3.connect(built_db)
    try:
        rows = conn.execute(
            "SELECT case_id FROM passages_fts WHERE passages_fts MATCH ?",
            ("strafuitvoering",),
        ).fetchall()
        other_case_id = conn.execute(
            "SELECT case_id FROM cases WHERE ecli = ?",
            ("ECLI:BE:GHCC:2025:ARR.001",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert rows
    assert all(row[0] != other_case_id for row in rows)


def test_passage_embeddings_one_row_per_nonempty_section(built_db: Path) -> None:
    """Every non-empty section of every valid case gets one embedding row."""
    conn = sqlite3.connect(built_db)
    try:
        rows = conn.execute(
            "SELECT passage_id, case_id, section, model_name, vector "
            "FROM passage_embeddings ORDER BY passage_id"
        ).fetchall()
    finally:
        conn.close()

    # Two valid fixtures, each with all four sections populated.
    assert len(rows) == 8
    sections_seen = {(row[1], row[2]) for row in rows}
    assert len(sections_seen) == 8  # no duplicates across (case_id, section)

    for _passage_id, _case_id, _section, model_name, vector_blob in rows:
        assert model_name == "fake-hash-embedder"
        vector = np.frombuffer(vector_blob, dtype=np.float32)
        assert vector.shape == (FAKE_EMBEDDING_DIM,)
        assert vector.dtype == np.float32


def test_passage_embeddings_share_rowid_with_fts(built_db: Path) -> None:
    """passage_embeddings.passage_id must equal the matching passages_fts rowid."""
    conn = sqlite3.connect(built_db)
    try:
        joined = conn.execute(
            "SELECT COUNT(*) FROM passage_embeddings pe "
            "JOIN passages_fts f ON f.rowid = pe.passage_id "
            "WHERE f.text = pe.text AND f.section = pe.section"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM passage_embeddings").fetchone()[0]
    finally:
        conn.close()

    assert joined == total
