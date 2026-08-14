"""Shared parsing for one ruling's Markdown file (frontmatter + sections).

Every source Markdown file has YAML frontmatter (matching ``CaseMetadata``)
followed by four ``##``-headed sections produced by the ingestion pipeline's
assembler (``src.ingestion.assemble``). Both ``src.indexing.build_index``
(building the searchable ``cases.db``) and ``src.site.build_site`` (rendering
per-case static HTML) need this exact same parsing, so it lives here once
rather than being duplicated or reached into across modules.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.schemas import (
    SECTION_ARGUMENTS,
    SECTION_FACTS,
    SECTION_REASONING,
    SECTION_RULING,
    CaseMetadata,
)

SECTION_HEADERS: tuple[tuple[str, str], ...] = (
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


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a Markdown document into its raw YAML frontmatter and body.
    Return ``(frontmatter_yaml, body)`` tuple.
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise MalformedFrontmatterError("No '---' delimited frontmatter block found")
    return match.group(1), text[match.end() :]


def parse_metadata(frontmatter_yaml: str) -> CaseMetadata:
    """Parse and validate a case's YAML frontmatter."""
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


def split_sections(body: str) -> dict[str, str]:
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
    for header, section in SECTION_HEADERS:
        start = body.find(header)
        if start != -1:
            positions.append((start, start + len(header), section))
    positions.sort(key=lambda p: p[0])

    sections: dict[str, str] = {}
    for i, (_start, header_end, section) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        sections[section] = body[header_end:end].strip()
    return sections


def parse_case_file(md_file: Path) -> tuple[CaseMetadata, dict[str, str]]:
    """Parse one ruling's Markdown file into its metadata and sections.

    Args:
        md_file: Path to the ruling's Markdown file.

    Returns:
        A ``(metadata, sections)`` tuple - ``sections`` maps section
        constant (see ``src.schemas``) to trimmed section text, per
        ``split_sections``.

    Raises:
        MalformedFrontmatterError: If the file has no frontmatter block, or
            its frontmatter fails to parse/validate.
    """
    text = md_file.read_text(encoding="utf-8")
    frontmatter_yaml, body = split_frontmatter(text)
    metadata = parse_metadata(frontmatter_yaml)
    sections = split_sections(body)
    return metadata, sections
