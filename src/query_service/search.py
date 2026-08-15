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

from src.db_schema import EMBEDDING_QUERY_PREFIX
from src.schemas import CaseSearchResult, ChunkResult
from src.sources import SOURCES

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

# Maximum number of matching chunks to include per case in the search response.
# Cases may have many chunks that match a query; exposing only the top few
# keeps the response concise while still showing the most relevant passages.
_MAX_CHUNKS_PER_CASE = 3


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
) -> list[tuple[int, int, str, str | None, str | None, int | None, str | None, str]]:
    """Rank passages by BM25 via the ``chunks_fts`` virtual table.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The raw user search string.
        limit: Maximum number of ranked passages to return.
        sources: Optional source keys to restrict results to.

    Returns:
        ``(chunk_id, case_id, section, paragraph_number, section_category,
        heading_level, parent_heading, text)`` tuples ordered by FTS5's
        BM25-derived ``rank`` (best first). Empty if ``query_text`` has no
        usable tokens.
    """
    match_query = _build_fts_match_query(query_text)
    if not match_query:
        return []
    source_sql, source_params = _source_filter_sql(sources)
    cursor = conn.execute(
        "SELECT chunks.chunk_id, chunks.case_id, chunks.section, "
        "chunks.paragraph_number, chunks.section_category, "
        "chunks.heading_level, chunks.parent_heading, chunks.text "
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
) -> list[tuple[int, int, str, str | None, str | None, int | None, str | None, str]]:
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
        ``(chunk_id, case_id, section, paragraph_number, section_category,
        heading_level, parent_heading, text)`` tuples ordered by similarity
        score (best first). Empty if there are no stored embeddings (e.g. a
        Phase 1 artifact that never ran the Phase 2 ``add_embeddings`` step).
    """
    source_sql, source_params = _source_filter_sql(sources)
    rows = conn.execute(
        "SELECT chunks.chunk_id, chunks.case_id, chunks.section, "
        "chunks.paragraph_number, chunks.section_category, "
        "chunks.heading_level, chunks.parent_heading, chunks.text, "
        "embeddings.vector "
        "FROM embeddings "
        "JOIN chunks ON chunks.chunk_id = embeddings.chunk_id "
        "JOIN cases ON cases.case_id = chunks.case_id "
        f"WHERE 1=1{source_sql}",
        source_params,
    ).fetchall()
    if not rows:
        return []

    # Apply the query prefix required by E5-class models. The passage prefix
    # is applied at index time by embed_passages; the query prefix must be
    # applied here at retrieval time. Both prefixes are defined in
    # src.db_schema so a model change updates both places atomically.
    query_vector = embed_fn([EMBEDDING_QUERY_PREFIX + query_text])[0].astype(np.float32)
    stored_vectors = np.stack([np.frombuffer(row[8], dtype=np.float32) for row in rows])
    scores = stored_vectors @ query_vector

    top_indices = np.argsort(-scores)[:limit]
    return [
        (rows[i][0], rows[i][1], rows[i][2], rows[i][3], rows[i][4],
         rows[i][5], rows[i][6], rows[i][7])
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
) -> list[CaseSearchResult]:
    """Run hybrid lexical + semantic search and return fused, ranked cases.

    Results are grouped by case: each returned item is one distinct case with
    its top ``_MAX_CHUNKS_PER_CASE`` matching chunks, ordered best-first.
    Cases are ranked by the score of their highest-ranked chunk.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The user's raw search string.
        embed_fn: Callable computing L2-normalized query embeddings, e.g.
            ``src.indexing.embeddings.embed_texts``. Injected rather than
            imported directly so tests can supply a lightweight fake.
        limit: Maximum number of distinct *cases* to return after fusion.
        sources: Optional judicial-body keys (e.g. ``["GHCC"]``) to restrict
            results to. ``None``/empty searches every registered body.

    Returns:
        ``CaseSearchResult`` objects sorted by descending best-chunk score,
        at most ``limit`` of them.
    """
    # Widen the candidate pool proportionally to ``limit`` so that even when
    # a single popular case dominates the top-k chunks we still surface enough
    # distinct cases to fill the page. The brute-force vector scan is
    # unaffected in cost (it scans all embeddings regardless); the FTS5 LIMIT
    # only bounds how many rows the virtual-table scan materialises.
    candidate_pool = max(_CANDIDATE_POOL_SIZE, limit * _MAX_CHUNKS_PER_CASE * 5)
    lexical_rows = _lexical_search(conn, query_text, candidate_pool, sources)
    semantic_rows = _semantic_search(conn, query_text, embed_fn, candidate_pool, sources)

    # Track each chunk's rank (1-based) in whichever list(s) it appears in,
    # plus enough chunk detail to build the final result without a second
    # per-chunk lookup.
    chunk_info: dict[
        int, tuple[int, str, str | None, str | None, int | None, str | None, str]
    ] = {}
    fused_scores: dict[int, float] = {}

    for ranked_list in (lexical_rows, semantic_rows):
        for rank, (
            chunk_id, case_id, section, paragraph_number,
            section_category, heading_level, parent_heading, text
        ) in enumerate(ranked_list, start=1):
            chunk_info.setdefault(
                chunk_id,
                (case_id, section, paragraph_number, section_category,
                 heading_level, parent_heading, text),
            )
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (
                _RRF_K + rank
            )

    if not fused_scores:
        return []

    # Group all scored chunks by their case, keeping only the top
    # ``_MAX_CHUNKS_PER_CASE`` per case (ordered best-first). The case's
    # representative score is the score of its highest-ranked chunk, which
    # also determines its position in the final ranked list.
    case_chunks: dict[
        int,
        list[tuple[float, str, str | None, str | None, int | None, str | None, str]],
    ] = {}
    for chunk_id, score in fused_scores.items():
        (case_id, section, paragraph_number, section_category,
         heading_level, parent_heading, text) = chunk_info[chunk_id]
        case_chunks.setdefault(case_id, []).append(
            (score, section, paragraph_number, section_category,
             heading_level, parent_heading, text)
        )

    # Sort each case's chunks by score descending, keep the top N.
    case_best_scores: dict[int, float] = {}
    for case_id, chunks in case_chunks.items():
        chunks.sort(key=lambda t: t[0], reverse=True)
        case_chunks[case_id] = chunks[:_MAX_CHUNKS_PER_CASE]
        case_best_scores[case_id] = chunks[0][0]

    # Rank cases by their best chunk score and take the top ``limit``.
    ranked_case_ids = sorted(
        case_best_scores, key=lambda cid: case_best_scores[cid], reverse=True
    )[:limit]

    cases_by_id = _fetch_cases(conn, set(ranked_case_ids))

    results = []
    for case_id in ranked_case_ids:
        case = cases_by_id.get(case_id)
        if case is None:
            # Defensive: the FOREIGN KEY constraint should prevent this, but
            # skip rather than crash a live query if the data is ever
            # inconsistent.
            continue
        chunks = [
            ChunkResult(
                section=section,
                section_category=section_category,
                heading_level=heading_level,
                parent_heading=parent_heading,
                paragraph_number=paragraph_number,
                excerpt=_truncate_excerpt(text),
                score=score,
            )
            for (score, section, paragraph_number, section_category,
                 heading_level, parent_heading, text) in case_chunks[case_id]
        ]
        source_config = SOURCES.get(case["source"])
        info_card = (
            source_config.build_info_card_url(case["arrest_number"], case["language"])
            if source_config is not None and source_config.build_info_card_url is not None
            else None
        )
        results.append(
            CaseSearchResult(
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
                source_pdf_url=case["source_pdf_url"],
                permalink_info_card=info_card,
                best_score=case_best_scores[case_id],
                chunks=chunks,
            )
        )
    return results
