"""Registry of judicial bodies ("sources") the pipeline knows how to handle.

The corpus is expected to grow beyond the Constitutional Court eventually
(e.g. the Council of State). Every case carries an explicit ``source`` key
(see ``src.schemas.CaseMetadata.source``), and each body's own paragraph
-numbering convention lives here, behind ``SourceConfig``, rather than
hard-coded into the chunker. Onboarding a new body means:

1. Writing that body's own discovery/extraction/assemble modules (courts
   publish differently - there is no shared scraper to reuse).
2. Working out its paragraph-numbering convention (if any) from real
   rulings and registering a new ``SourceConfig`` below.

Nothing in ``src.indexing.build_index`` or ``src.query_service`` needs to
change for either step - they read this registry, not a specific body's
conventions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SOURCE_CONSTITUTIONAL_COURT = "GHCC"


@dataclass(frozen=True)
class SourceConfig:
    """One judicial body's identity and paragraph-numbering convention.

    Attributes:
        key: Short, stable identifier stored on every case (``cases.source``).
        name: Human-readable name for display.
        paragraph_marker_re: Matches this body's paragraph-numbering markers
            at the start of a line, with the full numbered identifier (e.g.
            ``"B.7.3"``) as capture group 1. ``None`` if this body's rulings
            aren't known to number paragraphs at all, in which case every
            section is indexed as a single whole-section chunk.
    """

    key: str
    name: str
    paragraph_marker_re: re.Pattern[str] | None


# The Constitutional Court numbers points within its "-A-" (party arguments)
# and "-B-" (the Court's own reasoning) sections as "<letter>.<number>",
# nesting arbitrarily deep (e.g. "B.7.", "B.76.2.3."); the facts and
# operative-ruling sections are observed to never carry this numbering, so
# they fall back to a single whole-section chunk (see
# src.indexing.build_index).
_GHCC_PARAGRAPH_MARKER_RE = re.compile(r"(?m)^\s*([A-Z](?:\.\d+)+)\.\s+")

SOURCES: dict[str, SourceConfig] = {
    SOURCE_CONSTITUTIONAL_COURT: SourceConfig(
        key=SOURCE_CONSTITUTIONAL_COURT,
        name="Grondwettelijk Hof (Constitutional Court)",
        paragraph_marker_re=_GHCC_PARAGRAPH_MARKER_RE,
    ),
}


def get_source(key: str) -> SourceConfig:
    """Look up a registered judicial body by its ``source`` key.

    Args:
        key: A ``cases.source`` value, e.g. ``"GHCC"``.

    Returns:
        The matching ``SourceConfig``.

    Raises:
        ValueError: If ``key`` isn't registered in ``SOURCES``.
    """
    try:
        return SOURCES[key]
    except KeyError:
        raise ValueError(
            f"Unknown source key: {key!r}. Known sources: {sorted(SOURCES)}"
        ) from None
