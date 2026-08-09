"""Build the hybrid-search ``cases.db`` SQLite file from ruling Markdown.

Each source Markdown file has YAML frontmatter (matching ``CaseMetadata``)
followed by four ``##``-headed sections produced by the ingestion pipeline.
This module chunks each ruling one passage per section (whole-section
chunking, per the project's decision to avoid naive word-count/blank-line
splitting given how widely ruling lengths vary) and writes both the lexical
(FTS5) and vector representations of every passage.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

import numpy as np
import yaml
from pydantic import ValidationError

from src.db_schema import EMBEDDING_MODEL_NAME, initialize_database, insert_passage
from src.indexing.embeddings import embed_texts
from src.schemas import (
    SECTION_ARGUMENTS,
    SECTION_FACTS,
    SECTION_REASONING,
    SECTION_RULING,
    CaseMetadata,
)

logger = logging.getLogger(__name__)

# Exact section headers emitted by the ingestion pipeline's Markdown
# assembler, in document order, mapped to the section constants shared
# across the codebase via src.schemas.
_SECTION_HEADERS: tuple[tuple[str, str], ...] = (
    ("## Feiten en rechtspleging", SECTION_FACTS),
    ("## Standpunten van de partijen", SECTION_ARGUMENTS),
    ("## Beoordeling door het Hof", SECTION_REASONING),
    ("## Beschikking", SECTION_RULING),
)

# Matches the leading ``---\n<yaml>\n---`` frontmatter block. DOTALL so
# ``.`` spans the multi-line YAML body; non-greedy so it stops at the
# first closing delimiter rather than a later one inside the body text.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class MalformedFrontmatterError(ValueError):
    """Raised when a Markdown file's frontmatter cannot be parsed or validated."""


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a Markdown document into its raw YAML frontmatter and body.

    Args:
        text: Full contents of one source Markdown file.

    Returns:
        A ``(frontmatter_yaml, body)`` tuple.

    Raises:
        MalformedFrontmatterError: If the file has no ``---``-delimited
            frontmatter block at all.
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise MalformedFrontmatterError("No '---' delimited frontmatter block found")
    return match.group(1), text[match.end() :]


def _parse_metadata(frontmatter_yaml: str) -> CaseMetadata:
    """Parse and validate a case's YAML frontmatter.

    Args:
        frontmatter_yaml: The raw YAML text between the frontmatter delimiters.

    Returns:
        A validated ``CaseMetadata`` instance.

    Raises:
        MalformedFrontmatterError: If the YAML is unparsable, is not a
            mapping, or fails ``CaseMetadata`` validation (e.g. a missing
            required field).
    """
    try:
        raw = yaml.safe_load(frontmatter_yaml)
    except yaml.YAMLError as exc:
        raise MalformedFrontmatterError(f"Unparsable YAML frontmatter: {exc}") from exc

    if not isinstance(raw, dict):
        raise MalformedFrontmatterError("Frontmatter did not parse to a YAML mapping")

    try:
        return CaseMetadata.model_validate(raw)
    except ValidationError as exc:
        raise MalformedFrontmatterError(
            f"Frontmatter failed validation: {exc}"
        ) from exc


def _split_sections(body: str) -> dict[str, str]:
    """Split a ruling's body text into its structural sections.

    Sections are located by their exact header strings and sliced from the
    end of one header to the start of the next (or end of document). A
    section absent from the body (e.g. a header the ingestion pipeline
    didn't emit for this ruling) is simply omitted from the result rather
    than treated as an error - callers only insert passages for sections
    that are present and non-empty.

    Args:
        body: The Markdown body following the frontmatter block.

    Returns:
        A mapping of section constant (see ``src.schemas``) to trimmed
        section text, for whichever headers were found in ``body``.
    """
    positions: list[tuple[int, int, str]] = []
    for header, section in _SECTION_HEADERS:
        start = body.find(header)
        if start != -1:
            positions.append((start, start + len(header), section))
    positions.sort(key=lambda p: p[0])

    sections: dict[str, str] = {}
    for i, (_start, header_end, section) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        sections[section] = body[header_end:end].strip()
    return sections


def build_index(
    markdown_dir: Path,
    db_path: Path,
    embed_fn: Callable[[list[str]], np.ndarray] = embed_texts,
) -> None:
    """Build ``cases.db`` from a directory of ruling Markdown files.

    Args:
        markdown_dir: Directory containing one ``*.md`` file per ruling.
        db_path: Destination SQLite file. Overwritten if it already exists.
        embed_fn: Function computing embeddings for a batch of passage
            texts. Defaults to the real multilingual model in
            ``src.indexing.embeddings``; tests should inject a fast fake
            instead of loading that model. If the callable exposes a
            ``model_name`` attribute, that string is recorded in
            ``passage_embeddings.model_name``; otherwise
            ``EMBEDDING_MODEL_NAME`` is recorded.

    Malformed frontmatter (unparsable YAML, missing required
    ``CaseMetadata`` field) in a single file is logged and that file is
    skipped, rather than aborting the whole build.
    """
    if db_path.exists():
        db_path.unlink()

    model_name = getattr(embed_fn, "model_name", EMBEDDING_MODEL_NAME)

    conn = sqlite3.connect(db_path)
    try:
        initialize_database(conn)
        next_passage_id = 1
        for md_file in sorted(markdown_dir.glob("*.md")):
            try:
                next_passage_id = _index_file(
                    conn, md_file, embed_fn, model_name, next_passage_id
                )
            except MalformedFrontmatterError as exc:
                logger.warning("Skipping %s: %s", md_file, exc)
        conn.commit()
    finally:
        conn.close()


def _index_file(
    conn: sqlite3.Connection,
    md_file: Path,
    embed_fn: Callable[[list[str]], np.ndarray],
    model_name: str,
    next_passage_id: int,
) -> int:
    """Parse, validate, and insert one ruling's Markdown file.

    Args:
        conn: Open connection to the destination database.
        md_file: Path to the ruling's Markdown file.
        embed_fn: Embedding function, see ``build_index``.
        model_name: Model name string recorded alongside stored vectors.
        next_passage_id: Next free id to assign to a passage (shared rowid
            between ``passages_fts`` and ``passage_embeddings``).

    Returns:
        The next free passage id after inserting this file's sections.

    Raises:
        MalformedFrontmatterError: Propagated from parsing/validation so
            the caller can log and skip this file.
    """
    text = md_file.read_text(encoding="utf-8")
    frontmatter_yaml, body = _split_frontmatter(text)
    metadata = _parse_metadata(frontmatter_yaml)

    case_id = _insert_case(conn, metadata)

    sections = _split_sections(body)
    section_items = [(section, txt) for section, txt in sections.items() if txt]
    if not section_items:
        return next_passage_id

    texts = [txt for _section, txt in section_items]
    vectors = embed_fn(texts)

    passage_id = next_passage_id
    for (section, txt), vector in zip(section_items, vectors, strict=True):
        insert_passage(conn, passage_id, case_id, section, txt)
        conn.execute(
            "INSERT INTO passage_embeddings "
            "(passage_id, case_id, section, text, model_name, vector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                passage_id,
                case_id,
                section,
                txt,
                model_name,
                np.asarray(vector, dtype=np.float32).tobytes(),
            ),
        )
        passage_id += 1
    return passage_id


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
            ecli, arrest_number, role_number, file_slug, ruling_date,
            language, procedure_type, controlled_norm, outcome, keywords,
            source_pdf_url, title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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
