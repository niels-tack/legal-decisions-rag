"""Registry of judicial bodies ("sources") the pipeline knows how to handle.

The corpus is expected to grow beyond the Constitutional Court (e.g. the
Council of State). Every case carries an explicit ``source`` key (see
``src.schemas.CaseMetadata.source``), and each body's own conventions live
here behind ``SourceConfig``, rather than hard-coded into the pipeline.
Onboarding a new body means:

1. Writing that body's own discovery/extraction/assemble modules (courts
   publish differently - there is no shared scraper to reuse).
2. Working out its paragraph-numbering convention (if any) from real
   rulings and registering a new ``SourceConfig`` below with the correct
   ``paragraph_marker_re`` and ``section_headers``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SOURCE_CONSTITUTIONAL_COURT = "GHCC"
GHCC_SECTION_FACTS = "facts"
GHCC_SECTION_ARGUMENTS = "arguments"
GHCC_SECTION_REASONING = "reasoning"
GHCC_SECTION_RULING = "ruling"


@dataclass(frozen=True)
class SourceConfig:
    """One judicial body's identity and structural conventions.

    Attributes:
        key: Short, stable identifier stored on every case (``cases.source``).
        name: Human-readable name for display.
        paragraph_marker_re: Matches this body's paragraph-numbering markers
            at the start of a line, with the full numbered identifier (e.g.
            ``"B.7.3"``) as capture group 1. ``None`` if this body's rulings
            aren't known to number paragraphs at all, in which case every
            section is indexed as a single whole-section chunk.
        section_headers: Ordered ``(markdown_header, section_label)`` pairs
            that define this body's Markdown section structure. The
            ``markdown_header`` is the exact ``##``-prefixed string the
            assembler emits (and the parser splits on); ``section_label`` is
            the free-form string stored in ``chunks.section`` and used as an
            HTML anchor on case pages. Order must match document order so
            ``split_sections`` can slice between consecutive headers.
    """

    key: str
    name: str
    paragraph_marker_re: re.Pattern[str] | None
    section_headers: tuple[tuple[str, str], ...]


# Sections are indicated by "<letter>.<number>", nesting arbitrarily deep
# (e.g. "B.7.", "B.76.2.3.") for "-A-" (party arguments) and "-B-"
# (Court's reasoning). Facts and operative-ruling have no numbering, so
# they fall back to a single whole-section chunk.
_GHCC_PARAGRAPH_MARKER_RE = re.compile(r"(?m)^\s*([A-Z](?:\.\d+)+)\.\s+")

SOURCES: dict[str, SourceConfig] = {
    SOURCE_CONSTITUTIONAL_COURT: SourceConfig(
        key=SOURCE_CONSTITUTIONAL_COURT,
        name="Grondwettelijk Hof (Court Constitutionnel)",
        paragraph_marker_re=_GHCC_PARAGRAPH_MARKER_RE,
        section_headers=(
            ("## Feiten en rechtspleging", GHCC_SECTION_FACTS),
            ("## Standpunten van de partijen", GHCC_SECTION_ARGUMENTS),
            ("## Beoordeling door het Hof", GHCC_SECTION_REASONING),
            ("## Beschikking", GHCC_SECTION_RULING),
        ),
    ),
}


def get_source(key: str) -> SourceConfig:
    """Look up a registered judicial body by its ``source`` key."""
    try:
        return SOURCES[key]
    except KeyError:
        raise ValueError(
            f"Unknown source key: {key!r}. Known sources: {sorted(SOURCES)}"
        ) from None
