"""Build the Phase 1 BM25-only ``cases.db`` SQLite file from ruling Markdown.

Each source Markdown file has YAML frontmatter (matching ``CaseMetadata``)
followed by four ``##``-headed sections produced by the ingestion pipeline.
This module first splits each ruling into those four broad sections, then
chunks each section at its own numbered-paragraph granularity (e.g.
``B.7.3``) using the issuing body's marker pattern from
``src.sources.SOURCES`` - finer-grained than one chunk per section, since a
single section can itself run to hundreds of numbered points. A section (or
a body) with no numbering convention falls back to one whole-section chunk,
per the project's decision to avoid naive word-count/blank-line splitting
given how widely ruling lengths vary. It has no embedding dependency at all,
so the Phase 1 GitHub Actions build (which produces the artifact deployed
to GitHub Pages) never needs to install or run a sentence-embedding model.

Phase 2 layers vector embeddings on top of this same artifact via
``add_embeddings`` below, run as a separate, additive step.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

import numpy as np

from src.db_schema import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_PASSAGE_PREFIX,
    EMBEDDING_QUERY_PREFIX,
    initialize_database,
    insert_chunk,
    tune_for_range_access,
    upsert_model_meta,
)
from src.markdown_case import MalformedFrontmatterError, parse_case_file
from src.schemas import CaseMetadata
from src.sources import SourceConfig, get_source

logger = logging.getLogger(__name__)


def build_index(markdown_dir: Path, db_path: Path) -> None:
    """Build the Phase 1 ``cases.db`` (BM25 only) from a directory of Markdown.

    Args:
        markdown_dir: Directory containing one ``*.md`` file per ruling.
        db_path: Destination SQLite file. Overwritten if it already exists.

    Malformed frontmatter (unparsable YAML, missing required
    ``CaseMetadata`` field) in a single file is logged and that file is
    skipped, rather than aborting the whole build. ``VACUUM``/``ANALYZE``
    run once at the end so the on-disk page size matches
    ``src.db_schema.PAGE_SIZE`` and the query planner has fresh statistics.
    """
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        initialize_database(conn)
        next_chunk_id = 1
        for md_file in sorted(markdown_dir.glob("*.md")):
            try:
                next_chunk_id = _index_file(conn, md_file, next_chunk_id)
            except MalformedFrontmatterError as exc:
                logger.warning("Skipping %s: %s", md_file, exc)
        conn.commit()
        tune_for_range_access(conn)
    finally:
        conn.close()


def split_into_paragraphs(
    section_text: str, source_config: SourceConfig
) -> list[tuple[str | None, list[str], str]]:
    """Split one section's text into fine-grained numbered-paragraph chunks.

    Args:
        section_text: One section's trimmed body text (may be empty).
        source_config: The issuing body's config, whose
            ``paragraph_marker_re`` (if any) locates paragraph-numbering
            markers within ``section_text``.

    Returns:
        ``(paragraph_number, parent_numbers, text)`` tuples in document
        order. Falls back to a single ``(None, [], section_text)`` chunk
        when the body has no numbering convention, or the section simply
        has no numbered markers in it (e.g. the facts/operative-ruling
        sections of a Constitutional Court ruling). Any text preceding the
        first marker (e.g. a "-B-" divider line already captured as part
        of the section) is dropped if blank, or kept as its own
        unnumbered chunk otherwise. Empty if ``section_text`` is empty.
    """
    if not section_text:
        return []

    marker_re = source_config.paragraph_marker_re
    matches = list(marker_re.finditer(section_text)) if marker_re else []
    if not matches:
        return [(None, [], section_text)]

    chunks: list[tuple[str | None, list[str], str]] = []
    preamble = section_text[: matches[0].start()].strip()
    if preamble:
        chunks.append((None, [], preamble))

    for index, match in enumerate(matches):
        number = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            section_text
        )
        parts = number.split(".")
        parent_numbers = [".".join(parts[:i]) for i in range(1, len(parts))]
        chunks.append((number, parent_numbers, section_text[match.start() : end].strip()))
    return chunks


def _index_file(conn: sqlite3.Connection, md_file: Path, next_chunk_id: int) -> int:
    """Parse, validate, and insert one ruling's Markdown file.

    Args:
        conn: Open connection to the destination database.
        md_file: Path to the ruling's Markdown file.
        next_chunk_id: Next free id to assign to a chunk (shared rowid
            between ``chunks`` and ``chunks_fts``).

    Returns:
        The next free chunk id after inserting this file's sections.

    Raises:
        MalformedFrontmatterError: Propagated from parsing/validation so
            the caller can log and skip this file.
    """
    metadata, sections = parse_case_file(md_file)
    source_config = get_source(metadata.source)

    case_id = _insert_case(conn, metadata)

    chunk_id = next_chunk_id
    order = 0
    # heading_stack: list of (level, heading_key) for ancestor sections.
    # Maintained so each chunk knows its nearest ancestor at a lower level.
    heading_stack: list[tuple[int, str]] = []

    for section_key, section_text in sections.items():
        category = (
            source_config.heading_category_map.get(section_key)
            if source_config.heading_category_map
            else None
        )
        level = (
            source_config.heading_level_map.get(section_key)
            if source_config.heading_level_map
            else None
        )

        # Update the ancestor stack: pop any entries at the same or deeper level
        # so the parent is always a strictly shallower heading.
        if level is not None:
            heading_stack = [(lvl, h) for lvl, h in heading_stack if lvl < level]
        parent = heading_stack[-1][1] if heading_stack else None

        for paragraph_number, parent_numbers, chunk_text in split_into_paragraphs(
            section_text, source_config
        ):
            insert_chunk(
                conn,
                chunk_id,
                case_id,
                section_key,
                order,
                chunk_text,
                paragraph_number=paragraph_number,
                parent_numbers=parent_numbers,
                section_category=category,
                heading_level=level,
                parent_heading=parent,
            )
            chunk_id += 1
            order += 1

        # Push this section onto the stack after processing its chunks, so
        # sibling sections at the same level share the same parent rather
        # than each other.
        if level is not None:
            heading_stack.append((level, section_key))

    return chunk_id


def _insert_case(conn: sqlite3.Connection, metadata: CaseMetadata) -> int:
    """Insert one row into ``cases`` and return its generated ``case_id``.

    Args:
        conn: Open connection to the destination database.
        metadata: Validated frontmatter for the ruling.

    Returns:
        The ``case_id`` SQLite assigned to the new row.
    """
    cursor = conn.execute(
        """
        INSERT INTO cases (
            source, ecli, arrest_number, role_number, file_slug, ruling_date,
            language, procedure_type, controlled_norm, outcome, keywords,
            source_pdf_url, title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            metadata.source,
            metadata.ecli,
            metadata.arrest_number,
            metadata.role_number,
            metadata.file_slug,
            metadata.ruling_date.isoformat(),
            metadata.language,
            metadata.procedure_type,
            metadata.controlled_norm,
            metadata.outcome,
            json.dumps(metadata.keywords),
            metadata.source_pdf_url,
            metadata.title,
        ),
    )
    assert cursor.lastrowid is not None  # INSERT always yields a rowid
    return cursor.lastrowid


def add_embeddings(
    db_path: Path,
    embed_fn: Callable[[list[str]], np.ndarray] | None = None,
    batch_size: int = 64,
) -> int:
    """Phase 2 additive step: compute and store embeddings for every chunk.

    Populates the ``embeddings`` table for every ``chunks`` row that doesn't
    already have one, so this can be re-run safely on top of an existing
    artifact. After all vectors are stored, writes a ``model_meta`` row
    recording the model name, dimension, and the prefix strings required at
    query time - so the query service can verify it is using byte-identical
    weights and prefixes.

    Never invoked by the Phase 1 build path or its CI job; only the Phase 2
    index-build step (adding embeddings before uploading to Scaleway Object
    Storage) calls this.

    Args:
        db_path: Path to an existing ``cases.db`` built by ``build_index``.
        embed_fn: Callable computing L2-normalized embeddings for a batch of
            passage texts (already passage-prefixed if required). Defaults to
            ``src.indexing.embeddings.embed_passages``, imported lazily so
            that importing this module (and running the Phase 1 build)
            never requires ``sentence-transformers`` to be installed.
        batch_size: Number of chunk texts embedded per model call.

    Returns:
        The number of newly embedded chunks.
    """
    if embed_fn is None:
        from src.indexing.embeddings import embed_passages as embed_fn

    model_name = getattr(embed_fn, "model_name", EMBEDDING_MODEL_NAME)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT chunk_id, text FROM chunks "
            "WHERE chunk_id NOT IN (SELECT chunk_id FROM embeddings) "
            "ORDER BY chunk_id"
        ).fetchall()

        embedded_count = 0
        first_vector_dim: int | None = None
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors = embed_fn([text for _chunk_id, text in batch])
            if first_vector_dim is None and len(vectors):
                first_vector_dim = vectors.shape[1]
            conn.executemany(
                "INSERT INTO embeddings (chunk_id, model_name, vector) "
                "VALUES (?, ?, ?)",
                [
                    (
                        chunk_id,
                        model_name,
                        np.asarray(vector, dtype=np.float32).tobytes(),
                    )
                    for (chunk_id, _text), vector in zip(batch, vectors, strict=True)
                ],
            )
            embedded_count += len(batch)

        vector_dim = first_vector_dim or EMBEDDING_DIM
        upsert_model_meta(
            conn,
            model_name=model_name,
            vector_dim=vector_dim,
            query_prefix=EMBEDDING_QUERY_PREFIX,
            passage_prefix=EMBEDDING_PASSAGE_PREFIX,
        )
        conn.commit()
        return embedded_count
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the ``python -m`` entrypoint.

    Returns:
        Parsed arguments with ``markdown_dir`` and ``db_path`` as ``Path``.
    """
    parser = argparse.ArgumentParser(
        description="Build cases.db from a directory of ruling Markdown files."
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        required=True,
        help="Directory containing one *.md file per ruling.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        required=True,
        help="Destination SQLite file (overwritten if it exists).",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint: ``python -m src.indexing.build_index``."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = _parse_args()
    build_index(args.markdown_dir, args.db_path)


if __name__ == "__main__":
    main()
