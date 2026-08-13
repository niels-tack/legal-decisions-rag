"""Hybrid BM25 + vector search over a ``cases.db`` index.

Combines SQLite FTS5 lexical ranking with brute-force cosine similarity over
the ``passage_embeddings`` table, then fuses the two ranked lists with
Reciprocal Rank Fusion (RRF, k=60) so neither signal alone can dominate
before the caller's ``limit`` is applied.
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


def _lexical_search(
    conn: sqlite3.Connection, query_text: str, limit: int
) -> list[tuple[int, int, str, str]]:
    """Rank passages by BM25 via the ``passages_fts`` virtual table.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The raw user search string.
        limit: Maximum number of ranked passages to return.

    Returns:
        ``(passage_id, case_id, section, text)`` tuples ordered by FTS5's
        BM25-derived ``rank`` (best first). Empty if ``query_text`` has no
        usable tokens.
    """
    match_query = _build_fts_match_query(query_text)
    if not match_query:
        return []
    cursor = conn.execute(
        "SELECT rowid, case_id, section, text FROM passages_fts "
        "WHERE passages_fts MATCH ? ORDER BY rank LIMIT ?",
        (match_query, limit),
    )
    return cursor.fetchall()


def _semantic_search(
    conn: sqlite3.Connection,
    query_text: str,
    embed_fn: Callable[[list[str]], np.ndarray],
    limit: int,
) -> list[tuple[int, int, str, str]]:
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

    Returns:
        ``(passage_id, case_id, section, text)`` tuples ordered by
        similarity score (best first). Empty if there are no stored
        embeddings.
    """
    rows = conn.execute(
        "SELECT passage_id, case_id, section, text, vector FROM passage_embeddings"
    ).fetchall()
    if not rows:
        return []

    query_vector = embed_fn([query_text])[0].astype(np.float32)
    stored_vectors = np.stack([np.frombuffer(row[4], dtype=np.float32) for row in rows])
    scores = stored_vectors @ query_vector

    top_indices = np.argsort(-scores)[:limit]
    return [(rows[i][0], rows[i][1], rows[i][2], rows[i][3]) for i in top_indices]


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
) -> list[SearchResultItem]:
    """Run hybrid lexical + semantic search and return fused, ranked results.

    Args:
        conn: An open connection to the ``cases.db`` database.
        query_text: The user's raw search string.
        embed_fn: Callable computing L2-normalized query embeddings, e.g.
            ``src.indexing.embeddings.embed_texts``. Injected rather than
            imported directly so tests can supply a lightweight fake.
        limit: Maximum number of results to return after fusion.

    Returns:
        ``SearchResultItem`` objects sorted by descending fused RRF score,
        at most ``limit`` of them.
    """
    lexical_rows = _lexical_search(conn, query_text, _CANDIDATE_POOL_SIZE)
    semantic_rows = _semantic_search(conn, query_text, embed_fn, _CANDIDATE_POOL_SIZE)

    # Track each passage's rank (1-based) in whichever list(s) it appears in,
    # plus enough passage detail to build the final result without a second
    # per-passage lookup.
    passage_info: dict[int, tuple[int, str, str]] = {}
    fused_scores: dict[int, float] = {}

    for ranked_list in (lexical_rows, semantic_rows):
        for rank, (passage_id, case_id, section, text) in enumerate(
            ranked_list, start=1
        ):
            passage_info.setdefault(passage_id, (case_id, section, text))
            fused_scores[passage_id] = fused_scores.get(passage_id, 0.0) + 1.0 / (
                _RRF_K + rank
            )

    ranked_ids = sorted(fused_scores, key=lambda pid: fused_scores[pid], reverse=True)[
        :limit
    ]
    if not ranked_ids:
        return []

    case_ids = {passage_info[pid][0] for pid in ranked_ids}
    cases_by_id = _fetch_cases(conn, case_ids)

    results = []
    for passage_id in ranked_ids:
        case_id, section, text = passage_info[passage_id]
        case = cases_by_id.get(case_id)
        if case is None:
            # Defensive: the FOREIGN KEY constraint should prevent this, but
            # skip rather than crash a live query if the data is ever
            # inconsistent.
            continue
        results.append(
            SearchResultItem(
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
                excerpt=text,
                source_pdf_url=case["source_pdf_url"],
                score=fused_scores[passage_id],
            )
        )
    return results
