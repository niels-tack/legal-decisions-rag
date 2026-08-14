"""Hybrid BM25 + vector search over a ``cases.db`` index.

Combines SQLite FTS5 lexical ranking (over ``chunks_fts``, joined back to
``chunks`` for case/section context) with brute-force cosine similarity over
the ``embeddings`` table, then fuses the two ranked lists with Reciprocal
Rank Fusion (RRF, k=60) so neither signal alone can dominate before the
caller's ``limit`` is applied.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import numpy as np

from src.schemas import SearchResultItem

# Standard RRF smoothing constant: dampens the influence of very high ranks
# without needing per-corpus tuning.
_RRF_K = 60

# Depth of each individual ranked list considered before fusion. Wide enough
# to give RRF a meaningful pool to combine, small enough to keep the
# brute-force vector scan and FTS query cheap at this corpus size.
_CANDIDATE_POOL_SIZE = 50

# Response-size cap (part of the keyless public API's abuse protection,
# alongside per-IP rate limiting and CORS - see
# src.query_service.rate_limit): a whole ruling section can run to tens of
# thousands of characters, which the caller neither needs nor should be able
# to pull wholesale through the search endpoint.
_MAX_EXCERPT_CHARS = 2000


def _truncate_excerpt(text: str) -> str:
    """Cap a chunk's text at ``_MAX_EXCERPT_CHARS`` for the search response.

    Args:
        text: The full chunk text.

    Returns:
        ``text`` unchanged if short enough, otherwise truncated with a
        trailing ellipsis.
    """
    if len(text) <= _MAX_EXCERPT_CHARS:
        return text
    return text[:_MAX_EXCERPT_CHARS].rstrip() + "…"


def _build_fts_match_query(query_text: str) -> str:
    """Turn free-form user text into a safe FTS5 ``MATCH`` expression.

    Each whitespace-separated token is quoted individually and any literal
    double quote inside a token is escaped by doubling it, then the quoted
    tokens are joined with ``OR``. This treats the query as a bag of literal
    terms rather than passing it through FTS5's own query syntax, so
    characters like ``-`` or unbalanced quotes in arbitrary user input can't
    raise an FTS5 syntax error.

    Args:
        query_text: The raw user search string.

    Returns:
        An FTS5 ``MATCH`` expression, or an empty string if ``query_text``
        has no whitespace-separated tokens.
    """
    tokens = query_text.split()
    quoted = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens]
    return " OR ".join(quoted)


def _source_filter_sql(sources: list[str] | None) -> tuple[str, tuple[str, ...]]:
    """Build the optional ``cases.source IN (...)`` SQL fragment and params.

    Args:
        sources: Source keys to restrict results to (e.g. ``["GHCC"]``), or
            ``None``/empty for no filtering (every registered judicial
            body).

    Returns:
        A ``(sql_fragment, params)`` pair. ``sql_fragment`` is an empty
        string (and ``params`` an empty tuple) when ``sources`` is falsy, so
        callers can always append it after their base ``WHERE`` clause.
    """
    if not sources:
        return "", ()
    placeholders = ", ".join("?" for _ in sources)
    return f" AND cases.source IN ({placeholders})", tuple(sources)


def _lexical_search(
    conn: sqlite3.Connection,
    query_text: str,
    limit: int,
    sources: list[str] | None = None,
) -> list[tuple[int, int, str, str | None, str]]:
    """Rank passages by BM25 via the ``chunks_fts`` virtual table.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The raw user search string.
        limit: Maximum number of ranked passages to return.
        sources: Optional source keys to restrict results to.

    Returns:
        ``(chunk_id, case_id, section, paragraph_number, text)`` tuples
        ordered by FTS5's BM25-derived ``rank`` (best first). Empty if
        ``query_text`` has no usable tokens.
    """
    match_query = _build_fts_match_query(query_text)
    if not match_query:
        return []
    source_sql, source_params = _source_filter_sql(sources)
    cursor = conn.execute(
        "SELECT chunks.chunk_id, chunks.case_id, chunks.section, "
        "chunks.paragraph_number, chunks.text "
        "FROM chunks_fts "
        "JOIN chunks ON chunks.chunk_id = chunks_fts.rowid "
        "JOIN cases ON cases.case_id = chunks.case_id "
        f"WHERE chunks_fts MATCH ?{source_sql} ORDER BY rank LIMIT ?",
        (match_query, *source_params, limit),
    )
    return cursor.fetchall()


def _semantic_search(
    conn: sqlite3.Connection,
    query_text: str,
    embed_fn: Callable[[list[str]], np.ndarray],
    limit: int,
    sources: list[str] | None = None,
) -> list[tuple[int, int, str, str | None, str]]:
    """Rank passages by cosine similarity to the embedded query text.

    The corpus is small enough that a brute-force scan over every stored
    embedding is fast; no vector-index library is needed. Stored vectors are
    already L2-normalized (see ``src.indexing.embeddings.embed_texts``), so
    a plain dot product against a normalized query vector equals cosine
    similarity.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The raw user search string.
        embed_fn: Callable computing L2-normalized embeddings for a batch of
            texts, e.g. ``src.indexing.embeddings.embed_texts``.
        limit: Maximum number of ranked passages to return.
        sources: Optional source keys to restrict results to.

    Returns:
        ``(chunk_id, case_id, section, paragraph_number, text)`` tuples
        ordered by similarity score (best first). Empty if there are no
        stored embeddings (e.g. a Phase 1 artifact that never ran the
        Phase 2 ``add_embeddings`` step).
    """
    source_sql, source_params = _source_filter_sql(sources)
    rows = conn.execute(
        "SELECT chunks.chunk_id, chunks.case_id, chunks.section, "
        "chunks.paragraph_number, chunks.text, embeddings.vector "
        "FROM embeddings "
        "JOIN chunks ON chunks.chunk_id = embeddings.chunk_id "
        "JOIN cases ON cases.case_id = chunks.case_id "
        f"WHERE 1=1{source_sql}",
        source_params,
    ).fetchall()
    if not rows:
        return []

    query_vector = embed_fn([query_text])[0].astype(np.float32)
    stored_vectors = np.stack([np.frombuffer(row[5], dtype=np.float32) for row in rows])
    scores = stored_vectors @ query_vector

    top_indices = np.argsort(-scores)[:limit]
    return [
        (rows[i][0], rows[i][1], rows[i][2], rows[i][3], rows[i][4])
        for i in top_indices
    ]


def _fetch_cases(
    conn: sqlite3.Connection, case_ids: set[int]
) -> dict[int, sqlite3.Row]:
    """Load full metadata rows for a set of case ids.

    Args:
        conn: An open connection to the ``cases.db`` database.
        case_ids: The ``case_id`` values to look up.

    Returns:
        A mapping from ``case_id`` to its row in the ``cases`` table.
    """
    if not case_ids:
        return {}
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    placeholders = ", ".join("?" for _ in case_ids)
    cursor.execute(
        f"SELECT * FROM cases WHERE case_id IN ({placeholders})",
        tuple(case_ids),
    )
    return {row["case_id"]: row for row in cursor.fetchall()}


def hybrid_search(
    conn: sqlite3.Connection,
    query_text: str,
    embed_fn: Callable[[list[str]], np.ndarray],
    limit: int = 5,
    sources: list[str] | None = None,
) -> list[SearchResultItem]:
    """Run hybrid lexical + semantic search and return fused, ranked results.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The user's raw search string.
        embed_fn: Callable computing L2-normalized query embeddings, e.g.
            ``src.indexing.embeddings.embed_texts``. Injected rather than
            imported directly so tests can supply a lightweight fake.
        limit: Maximum number of results to return after fusion.
        sources: Optional judicial-body keys (e.g. ``["GHCC"]``) to restrict
            results to. ``None``/empty searches every registered body.

    Returns:
        ``SearchResultItem`` objects sorted by descending fused RRF score,
        at most ``limit`` of them.
    """
    lexical_rows = _lexical_search(conn, query_text, _CANDIDATE_POOL_SIZE, sources)
    semantic_rows = _semantic_search(
        conn, query_text, embed_fn, _CANDIDATE_POOL_SIZE, sources
    )

    # Track each chunk's rank (1-based) in whichever list(s) it appears in,
    # plus enough chunk detail to build the final result without a second
    # per-chunk lookup.
    chunk_info: dict[int, tuple[int, str, str | None, str]] = {}
    fused_scores: dict[int, float] = {}

    for ranked_list in (lexical_rows, semantic_rows):
        for rank, (chunk_id, case_id, section, paragraph_number, text) in enumerate(
            ranked_list, start=1
        ):
            chunk_info.setdefault(chunk_id, (case_id, section, paragraph_number, text))
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (
                _RRF_K + rank
            )

    ranked_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)[
        :limit
    ]
    if not ranked_ids:
        return []

    case_ids = {chunk_info[cid][0] for cid in ranked_ids}
    cases_by_id = _fetch_cases(conn, case_ids)

    results = []
    for chunk_id in ranked_ids:
        case_id, section, paragraph_number, text = chunk_info[chunk_id]
        case = cases_by_id.get(case_id)
        if case is None:
            # Defensive: the FOREIGN KEY constraint should prevent this, but
            # skip rather than crash a live query if the data is ever
            # inconsistent.
            continue
        results.append(
            SearchResultItem(
                source=case["source"],
                ecli=case["ecli"],
                arrest_number=case["arrest_number"],
                role_number=case["role_number"],
                case_number=case["file_slug"],
                ruling_date=case["ruling_date"],
                language=case["language"],
                procedure_type=case["procedure_type"],
                controlled_norm=case["controlled_norm"],
                outcome=case["outcome"],
                title=case["title"],
                section=section,
                paragraph_number=paragraph_number,
                excerpt=_truncate_excerpt(text),
                source_pdf_url=case["source_pdf_url"],
                score=fused_scores[chunk_id],
            )
        )
    return results
