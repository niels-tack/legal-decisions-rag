"""Unit tests for ``src.query_service.search``.

Exercises ``hybrid_search`` directly against the fixture database (bypassing
HTTP) and separately checks the FTS5 query-escaping helper, since a naive
unescaped query is exactly the kind of input that would otherwise raise an
FTS5 syntax error.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.db_schema import initialize_database
from src.query_service.search import _build_fts_match_query, hybrid_search
from tests.query_service.conftest import fake_embed_fn


def test_build_fts_match_query_quotes_and_joins_tokens() -> None:
    """Tokens are individually quoted and joined with OR."""
    assert _build_fts_match_query("milieu vergunning") == '"milieu" OR "vergunning"'


def test_build_fts_match_query_escapes_embedded_quotes() -> None:
    """A literal double quote inside a token is doubled, not left bare."""
    result = _build_fts_match_query('foo"bar')

    assert result == '"foo""bar"'


def test_build_fts_match_query_empty_input_returns_empty_string() -> None:
    """Whitespace-only input has no tokens to quote."""
    assert _build_fts_match_query("   ") == ""


def test_hybrid_search_lexical_match_returns_expected_case(
    fixture_db_path: Path,
) -> None:
    """A query with an exact lexical hit surfaces that passage's case."""
    conn = sqlite3.connect(str(fixture_db_path))
    try:
        results = hybrid_search(conn, "omgevingsvergunning", fake_embed_fn, limit=5)
    finally:
        conn.close()

    assert results
    top = results[0]
    assert top.source == "GHCC"
    assert top.ecli == "ECLI:BE:GHCC:2025:ARR.001"
    assert top.case_number == "2025-001n"
    assert top.chunks
    assert top.chunks[0].section == "reasoning"
    assert top.chunks[0].paragraph_number == "B.7"


def test_hybrid_search_semantic_only_match(fixture_db_path: Path) -> None:
    """A query with no lexical overlap can still match via embeddings.

    ``pensioen`` steers the fake embedder toward the pension fixture's
    vector, but the literal token doesn't appear in that passage's text, so
    a hit here proves the semantic branch (not just FTS) contributes.
    """
    conn = sqlite3.connect(str(fixture_db_path))
    try:
        results = hybrid_search(conn, "pensioen", fake_embed_fn, limit=5)
    finally:
        conn.close()

    assert results
    assert results[0].ecli == "ECLI:BE:GHCC:2025:ARR.002"
    assert results[0].chunks
    assert results[0].chunks[0].paragraph_number is None


def test_hybrid_search_filters_by_source(fixture_db_path: Path) -> None:
    """The optional ``sources`` filter restricts results to matching bodies.

    Scoping the same "verkeersboete" query to GHCC must never surface the
    OTHER-sourced case, even via the semantic branch's weak-match ranking
    (see ``test_hybrid_search_empty_index_returns_empty_list`` for why a
    nonempty embeddings pool always ranks *something*) - it can only be
    excluded by the source filter actually narrowing the candidate pool,
    not by its similarity score happening to be low.
    """
    conn = sqlite3.connect(str(fixture_db_path))
    try:
        ghcc_only = hybrid_search(
            conn, "verkeersboete", fake_embed_fn, limit=5, sources=["GHCC"]
        )
        other_only = hybrid_search(
            conn, "verkeersboete", fake_embed_fn, limit=5, sources=["OTHER"]
        )
    finally:
        conn.close()

    assert all(result.source == "GHCC" for result in ghcc_only)
    assert other_only
    assert other_only[0].source == "OTHER"
    assert other_only[0].ecli == "ECLI:BE:OTHER:2025:ARR.004"


def test_hybrid_search_respects_limit(fixture_db_path: Path) -> None:
    """Fusion never returns more than ``limit`` results."""
    conn = sqlite3.connect(str(fixture_db_path))
    try:
        results = hybrid_search(conn, "de het van voor", fake_embed_fn, limit=2)
    finally:
        conn.close()

    assert len(results) <= 2


def test_hybrid_search_empty_index_returns_empty_list() -> None:
    """Against an empty index (no passages at all), nothing can be found.

    Uses a fresh in-memory database rather than the shared fixture, since
    the fixture's brute-force vector scan ranks *all* stored passages (even
    weak matches) whenever any embeddings exist at all - a genuinely empty
    result only happens when there is no data to rank in the first place.
    """
    conn = sqlite3.connect(":memory:")
    try:
        initialize_database(conn)
        results = hybrid_search(conn, "xylophone quokka zzz", fake_embed_fn, limit=5)
    finally:
        conn.close()

    assert results == []
