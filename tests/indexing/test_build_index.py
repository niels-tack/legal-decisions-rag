"""Tests for src.indexing.build_index against small synthetic fixtures.

The Phase 1 build path (``build_index``) has no embedding dependency at
all, so these tests never touch sentence-transformers. ``add_embeddings``
(the separate Phase 2 step) is exercised with a deterministic fake embedder
so it stays fast and hermetic too.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from src.indexing.build_index import add_embeddings, build_index, split_into_paragraphs
from src.sources import SOURCE_CONSTITUTIONAL_COURT, SourceConfig, get_source

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FAKE_EMBEDDING_DIM = 8
_NO_NUMBERING_SOURCE = SourceConfig(
    key="TEST_NO_NUMBERING",
    name="Test source with no numbering",
    paragraph_marker_re=None,
    section_headers=(),
)


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


# Exposed so add_embeddings records this string instead of the real
# EMBEDDING_MODEL_NAME, proving the model-name-reporting hook works.
fake_embed_texts.model_name = "fake-hash-embedder"


@pytest.fixture
def built_db(tmp_path: Path) -> Path:
    """Build a Phase 1 (BM25-only) test database from the fixtures directory."""
    db_path = tmp_path / "cases.db"
    build_index(FIXTURES_DIR, db_path)
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


def test_page_size_is_tuned_for_range_access(built_db: Path) -> None:
    """The built database must use the range-request-tuned page size."""
    conn = sqlite3.connect(built_db)
    try:
        (page_size,) = conn.execute("PRAGMA page_size").fetchone()
    finally:
        conn.close()

    assert page_size == 1024


def test_no_embeddings_are_written_by_the_phase_1_build(built_db: Path) -> None:
    """The Phase 1 build never populates the reserved embeddings table."""
    conn = sqlite3.connect(built_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    finally:
        conn.close()

    assert count == 0


def test_fts_match_finds_expected_case(built_db: Path) -> None:
    """A keyword unique to one fixture's facts section should be found via FTS5."""
    conn = sqlite3.connect(built_db)
    try:
        rows = conn.execute(
            "SELECT chunks.case_id, chunks.section FROM chunks_fts "
            "JOIN chunks ON chunks.chunk_id = chunks_fts.rowid "
            "WHERE chunks_fts MATCH ?",
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
            "SELECT chunks.case_id FROM chunks_fts "
            "JOIN chunks ON chunks.chunk_id = chunks_fts.rowid "
            "WHERE chunks_fts MATCH ?",
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


def test_chunk_order_preserves_document_order(built_db: Path) -> None:
    """Each case's chunks are numbered 0..n-1 in the order sections appear."""
    conn = sqlite3.connect(built_db)
    try:
        case_id = conn.execute(
            "SELECT case_id FROM cases WHERE ecli = ?",
            ("ECLI:BE:GHCC:2025:ARR.001",),
        ).fetchone()[0]
        orders = [
            row[0]
            for row in conn.execute(
                "SELECT chunk_order FROM chunks WHERE case_id = ? ORDER BY chunk_id",
                (case_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    assert orders == list(range(len(orders)))


def test_add_embeddings_populates_one_row_per_chunk(built_db: Path) -> None:
    """Every chunk gets exactly one embedding row after add_embeddings runs."""
    embedded_count = add_embeddings(built_db, embed_fn=fake_embed_texts)

    conn = sqlite3.connect(built_db)
    try:
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        rows = conn.execute(
            "SELECT chunk_id, model_name, vector FROM embeddings ORDER BY chunk_id"
        ).fetchall()
    finally:
        conn.close()

    assert embedded_count == chunk_count
    assert len(rows) == chunk_count
    for _chunk_id, model_name, vector_blob in rows:
        assert model_name == "fake-hash-embedder"
        vector = np.frombuffer(vector_blob, dtype=np.float32)
        assert vector.shape == (FAKE_EMBEDDING_DIM,)
        assert vector.dtype == np.float32


def test_add_embeddings_is_idempotent(built_db: Path) -> None:
    """Re-running add_embeddings skips chunks that already have an embedding."""
    add_embeddings(built_db, embed_fn=fake_embed_texts)

    second_run_count = add_embeddings(built_db, embed_fn=fake_embed_texts)

    assert second_run_count == 0


def test_source_is_recorded_per_case(built_db: Path) -> None:
    """Every valid case records the judicial body that issued it."""
    conn = sqlite3.connect(built_db)
    try:
        sources = {row[0] for row in conn.execute("SELECT DISTINCT source FROM cases")}
    finally:
        conn.close()

    assert sources == {SOURCE_CONSTITUTIONAL_COURT}


def test_section_with_no_numbering_is_one_whole_chunk(built_db: Path) -> None:
    """Case 001's sections have no A./B. markers, so each stays one chunk."""
    conn = sqlite3.connect(built_db)
    try:
        case_id = conn.execute(
            "SELECT case_id FROM cases WHERE ecli = ?",
            ("ECLI:BE:GHCC:2025:ARR.001",),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT section, paragraph_number, parent_numbers FROM chunks "
            "WHERE case_id = ? ORDER BY chunk_id",
            (case_id,),
        ).fetchall()
    finally:
        conn.close()

    assert [row[0] for row in rows] == [
        "facts",
        "arguments",
        "reasoning",
        "ruling",
    ]
    assert all(row[1] is None for row in rows)
    assert all(json.loads(row[2]) == [] for row in rows)


def test_numbered_section_splits_into_paragraph_chunks_with_hierarchy(
    built_db: Path,
) -> None:
    """Case 002's reasoning section splits at each B.x marker, with ancestors."""
    conn = sqlite3.connect(built_db)
    try:
        case_id = conn.execute(
            "SELECT case_id FROM cases WHERE ecli = ?",
            ("ECLI:BE:GHCC:2025:ARR.002",),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT paragraph_number, parent_numbers, text FROM chunks "
            "WHERE case_id = ? AND section = 'reasoning' ORDER BY chunk_id",
            (case_id,),
        ).fetchall()
    finally:
        conn.close()

    assert [row[0] for row in rows] == ["B.1", "B.1.1", "B.2"]
    assert [json.loads(row[1]) for row in rows] == [["B"], ["B", "B.1"], ["B"]]
    assert rows[0][2].startswith("B.1.  Het Hof stelt vast")
    assert rows[1][2].startswith("B.1.1.  De bestreden bepaling")


def test_split_into_paragraphs_falls_back_when_no_marker_pattern() -> None:
    """A source with no numbering convention yields one whole-section chunk."""
    result = split_into_paragraphs("Some plain section text.", _NO_NUMBERING_SOURCE)

    assert result == [(None, [], "Some plain section text.")]


def test_split_into_paragraphs_empty_section_yields_no_chunks() -> None:
    """An empty section (missing in the source ruling) yields zero chunks."""
    assert split_into_paragraphs("", get_source(SOURCE_CONSTITUTIONAL_COURT)) == []


def test_split_into_paragraphs_keeps_nonblank_preamble_as_unnumbered_chunk() -> None:
    """Text before the first marker is kept as its own chunk if non-blank."""
    source_config = get_source(SOURCE_CONSTITUTIONAL_COURT)

    result = split_into_paragraphs(
        "- B -\nB.1.  Eerste punt.\nB.2.  Tweede punt.", source_config
    )

    assert result[0] == (None, [], "- B -")
    assert result[1] == ("B.1", ["B"], "B.1.  Eerste punt.")
    assert result[2] == ("B.2", ["B"], "B.2.  Tweede punt.")


def test_split_into_paragraphs_derives_multi_level_hierarchy() -> None:
    """A deeply nested identifier's ancestors are all its proper prefixes."""
    source_config = get_source(SOURCE_CONSTITUTIONAL_COURT)

    result = split_into_paragraphs("B.76.2.3.  Diep genest punt.", source_config)

    assert result == [
        ("B.76.2.3", ["B", "B.76", "B.76.2"], "B.76.2.3.  Diep genest punt.")
    ]


def test_split_into_paragraphs_accepts_missing_period_before_uppercase_text() -> None:
    """GHCC paragraph markers may omit their period before a new sentence."""
    source_config = get_source(SOURCE_CONSTITUTIONAL_COURT)

    result = split_into_paragraphs(
        "B.1. Eerste punt.\nB.2 Tweede punt.\nB.2.1 vermeld in een verwijzing.",
        source_config,
    )

    assert result == [
        ("B.1", ["B"], "B.1. Eerste punt."),
        (
            "B.2",
            ["B"],
            "B.2 Tweede punt.\nB.2.1 vermeld in een verwijzing.",
        ),
    ]
