"""Shared parsing for one ruling's Markdown file (frontmatter + sections).

Every source Markdown file has YAML frontmatter (matching ``CaseMetadata``)
followed by ``##``-headed sections produced by the ingestion pipeline's
assembler (``src.ingestion.assemble``).

Section headers are source-specific: each judicial body defines its own
``##``-headed structure via ``src.sources.SourceConfig.section_headers``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.schemas import CaseMetadata
from src.sources import SourceConfig, get_source

# Matches the leading ``---\n<yaml>\n---`` frontmatter block. DOTALL so
# ``.`` spans the multi-line YAML body; non-greedy so it stops at the
# first closing delimiter rather than a later one inside the body text.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class MalformedFrontmatterError(ValueError):
    """Raised when a Markdown file's frontmatter cannot be parsed or validated."""


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a Markdown document into its raw YAML frontmatter and body.

    Args:
        text: The full Markdown document text.

    Returns:
        ``(frontmatter_yaml, body)`` tuple.

    Raises:
        MalformedFrontmatterError: If no ``---`` delimited block is found.
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise MalformedFrontmatterError("No '---' delimited frontmatter block found")
    return match.group(1), text[match.end():]


def parse_metadata(frontmatter_yaml: str) -> CaseMetadata:
    """Parse and validate a case's YAML frontmatter.

    Args:
        frontmatter_yaml: The raw YAML string between the ``---`` delimiters.

    Returns:
        A validated ``CaseMetadata`` instance.

    Raises:
        MalformedFrontmatterError: If the YAML is unparsable, not a mapping,
            or fails ``CaseMetadata`` validation.
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


_DYNAMIC_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def split_sections(body: str, source_config: SourceConfig) -> dict[str, str]:
    """Split a ruling's body text into its structural sections.

    Two modes, selected by ``source_config.dynamic_sections``:

    - **Fixed** (``dynamic_sections=False``): splits on the exact
      ``##``-prefixed strings listed in ``source_config.section_headers``.
      The dict keys are the corresponding section labels (e.g. ``"facts"``
      for GHCC). Sections absent from the body are omitted from the result.
    - **Dynamic** (``dynamic_sections=True``): splits on *any* ``## ``-
      prefixed line found in the body, keeping the heading text verbatim as
      the dict key. Used for courts like RVS whose heading set varies per
      ruling and cannot be enumerated in advance.

    In both modes the dict is ordered by document position and values are
    trimmed of leading/trailing whitespace.

    Args:
        body: The Markdown body following the frontmatter block.
        source_config: The issuing body's config.

    Returns:
        A mapping of section key to trimmed section text.
    """
    if source_config.dynamic_sections:
        matches = list(_DYNAMIC_SECTION_RE.finditer(body))
        sections: dict[str, str] = {}
        for i, match in enumerate(matches):
            heading = match.group(1).strip()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            sections[heading] = body[match.end() : end].strip()
        return sections

    positions: list[tuple[int, int, str]] = []
    for header, section_label in source_config.section_headers:
        start = body.find(header)
        if start != -1:
            positions.append((start, start + len(header), section_label))
    positions.sort(key=lambda p: p[0])

    sections = {}
    for i, (_start, header_end, section_label) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        sections[section_label] = body[header_end:end].strip()
    return sections


def parse_case_file(md_file: Path) -> tuple[CaseMetadata, dict[str, str]]:
    """Parse one ruling's Markdown file into its metadata and sections.

    Derives the section structure from the case's own ``source`` field, so
    no caller needs to know or supply the issuing body's conventions.

    Args:
        md_file: Path to the ruling's Markdown file.

    Returns:
        ``(metadata, sections)`` where ``sections`` maps section label to
        trimmed section text, keyed by the source's own label strings.

    Raises:
        MalformedFrontmatterError: Propagated from ``split_frontmatter`` or
            ``parse_metadata`` if the file is malformed.
        ValueError: If the ``source`` key in the frontmatter is not
            registered in ``src.sources.SOURCES``.
    """
    text = md_file.read_text(encoding="utf-8")
    frontmatter_yaml, body = split_frontmatter(text)
    metadata = parse_metadata(frontmatter_yaml)
    source_config = get_source(metadata.source)
    sections = split_sections(body, source_config)
    return metadata, sections
