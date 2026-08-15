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
   ``paragraph_marker_re``, ``section_headers`` or ``dynamic_sections``,
   and ``heading_category_map``.

Cross-court category vocabulary
--------------------------------
Section headings differ per body (e.g. GHCC uses "Beoordeling door het Hof"
while RVS uses "Beoordeling van het middel"), but we want a single filterable
vocabulary across all courts. The ``heading_category_map`` on each
``SourceConfig`` maps the body's own heading/section keys to one of the
``CATEGORY_*`` constants below. Chunks whose heading is not in the map get
``section_category = None``; callers should treat that as "unknown".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Cross-court section category constants
# ---------------------------------------------------------------------------

CATEGORY_FACTS = "facts"
CATEGORY_ARGUMENTS = "arguments"
CATEGORY_REASONING = "reasoning"
CATEGORY_OPERATIVE = "operative"
CATEGORY_ADMISSIBILITY = "admissibility"
CATEGORY_JURISDICTION = "jurisdiction"
CATEGORY_SUSPENSION = "suspension"
CATEGORY_MIDDELEN = "middelen"

# ---------------------------------------------------------------------------
# Grondwettelijk Hof / Constitutional Court (GHCC)
# ---------------------------------------------------------------------------

SOURCE_CONSTITUTIONAL_COURT = "GHCC"
GHCC_SECTION_FACTS = "facts"
GHCC_SECTION_ARGUMENTS = "arguments"
GHCC_SECTION_REASONING = "reasoning"
GHCC_SECTION_RULING = "ruling"

# ---------------------------------------------------------------------------
# Raad van State / Council of State (RVS)
# ---------------------------------------------------------------------------

SOURCE_COUNCIL_OF_STATE = "RVS"

# Category map for RVS headings: heading text (stripped, verbatim as it will
# appear in the Markdown body after the assemble step) → cross-court category.
#
# Design notes:
# - Keys are the *verbatim* heading strings kept in the assembled Markdown,
#   not normalized variants. The assemble step writes headings as-found; the
#   indexer looks them up here for metadata only.
# - Unknown headings (not in the map) are indexed with section_category=None.
#   This is intentional: the corpus is large and inconsistent, so the map
#   covers the known cases while remaining open to new patterns.
# - Ordinal middelen headings ("Eerste middel" … "Tiende middel") and their
#   "Het Xe middel" variants are listed up to a plausible maximum; higher
#   ordinals (rare in practice) will just get section_category=None.
# - Sub-parts ("Eerste onderdeel" etc.) and "Onderzoek van het Xe middel"
#   forms all map to CATEGORY_MIDDELEN so they stay findable via category
#   filter alongside the top-level ground headings.
_RVS_HEADING_CATEGORY_MAP: dict[str, str] = {
    # --- Facts / case data ------------------------------------------------
    "De gegevens van de zaak": CATEGORY_FACTS,
    "Feiten": CATEGORY_FACTS,
    "De feiten": CATEGORY_FACTS,
    # --- Jurisdiction -----------------------------------------------------
    "De rechtsmacht van de Raad van State": CATEGORY_JURISDICTION,
    "Rechtsmacht van de Raad van State": CATEGORY_JURISDICTION,
    "Exceptie betreffende de rechtsmacht": CATEGORY_JURISDICTION,
    # --- Admissibility ----------------------------------------------------
    "De ontvankelijkheid": CATEGORY_ADMISSIBILITY,
    "Ontvankelijkheid van het beroep": CATEGORY_ADMISSIBILITY,
    "Ontvankelijkheid van de beroepen": CATEGORY_ADMISSIBILITY,
    "Ontvankelijkheid van de vordering": CATEGORY_ADMISSIBILITY,
    "Ontvankelijkheid – belang": CATEGORY_ADMISSIBILITY,
    "De exceptie": CATEGORY_ADMISSIBILITY,
    "Exceptie": CATEGORY_ADMISSIBILITY,
    "Excepties": CATEGORY_ADMISSIBILITY,
    "Uiteenzetting van de exceptie": CATEGORY_ADMISSIBILITY,
    # --- Suspension conditions --------------------------------------------
    "De grondvoorwaarden voor de schorsing": CATEGORY_SUSPENSION,
    "De schorsingsvoorwaarden": CATEGORY_SUSPENSION,
    "Schorsingsvoorwaarden": CATEGORY_SUSPENSION,
    "Herinnering aan de schorsingsvoorwaarden": CATEGORY_SUSPENSION,
    # --- Party standpoints ------------------------------------------------
    "Standpunt van de partijen": CATEGORY_ARGUMENTS,
    "Uiteenzetting van het middel": CATEGORY_ARGUMENTS,
    "Betwisting door verzoekende partij": CATEGORY_ARGUMENTS,
    # --- Grounds (middelen) - top-level ordinal forms ---------------------
    "Enig middel": CATEGORY_MIDDELEN,
    "Eerste middel": CATEGORY_MIDDELEN,
    "Tweede middel": CATEGORY_MIDDELEN,
    "Derde middel": CATEGORY_MIDDELEN,
    "Vierde middel": CATEGORY_MIDDELEN,
    "Vijfde middel": CATEGORY_MIDDELEN,
    "Zesde middel": CATEGORY_MIDDELEN,
    "Zevende middel": CATEGORY_MIDDELEN,
    "Achtste middel": CATEGORY_MIDDELEN,
    "Negende middel": CATEGORY_MIDDELEN,
    "Tiende middel": CATEGORY_MIDDELEN,
    # --- Grounds - "Het Xe middel" variants ------------------------------
    "Het enige middel": CATEGORY_MIDDELEN,
    "Het eerste middel": CATEGORY_MIDDELEN,
    "Het tweede middel": CATEGORY_MIDDELEN,
    "Het derde middel": CATEGORY_MIDDELEN,
    "Het vierde middel": CATEGORY_MIDDELEN,
    "Het vijfde middel": CATEGORY_MIDDELEN,
    "Het zesde middel": CATEGORY_MIDDELEN,
    "Het zevende middel": CATEGORY_MIDDELEN,
    "Het achtste middel": CATEGORY_MIDDELEN,
    "Het negende middel": CATEGORY_MIDDELEN,
    "Het tiende middel": CATEGORY_MIDDELEN,
    # --- Grounds - "Onderzoek van het Xe middel" forms -------------------
    "Onderzoek van de middelen": CATEGORY_MIDDELEN,
    "Onderzoek van het enige middel": CATEGORY_MIDDELEN,
    "Onderzoek van het eerste middel": CATEGORY_MIDDELEN,
    "Onderzoek van het tweede middel": CATEGORY_MIDDELEN,
    "Onderzoek van het derde middel": CATEGORY_MIDDELEN,
    "Onderzoek van het vierde middel": CATEGORY_MIDDELEN,
    "Onderzoek van het vijfde middel": CATEGORY_MIDDELEN,
    "Onderzoek van het zesde middel": CATEGORY_MIDDELEN,
    "Onderzoek van het zevende middel": CATEGORY_MIDDELEN,
    "Onderzoek van het achtste middel": CATEGORY_MIDDELEN,
    "Onderzoek van het negende middel": CATEGORY_MIDDELEN,
    "Onderzoek van het tiende middel": CATEGORY_MIDDELEN,
    # --- Grounds - sub-parts (onderdelen) --------------------------------
    "Eerste onderdeel": CATEGORY_MIDDELEN,
    "Tweede onderdeel": CATEGORY_MIDDELEN,
    "Derde onderdeel": CATEGORY_MIDDELEN,
    "Vierde onderdeel": CATEGORY_MIDDELEN,
    "Vijfde onderdeel": CATEGORY_MIDDELEN,
    # --- Merits (gegrondheid) --------------------------------------------
    "De gegrondheid van het beroep": CATEGORY_MIDDELEN,
    "De gegrondheid": CATEGORY_MIDDELEN,
    # --- Court's assessment / reasoning ----------------------------------
    "Beoordeling van het middel": CATEGORY_REASONING,
    "Beoordeling": CATEGORY_REASONING,
    # --- Operative ruling ------------------------------------------------
    "OM DIE REDENEN": CATEGORY_OPERATIVE,
    "BESLIST DE RAAD VAN STATE :": CATEGORY_OPERATIVE,
}


@dataclass(frozen=True)
class SourceConfig:
    """One judicial body's identity and structural conventions.

    Attributes:
        key: Short, stable identifier stored on every case (``cases.source``).
        name: Human-readable name for display.
        paragraph_marker_re: Matches this body's paragraph-numbering markers
            at the start of a line, with the full numbered identifier (e.g.
            ``"B.7.3"`` for GHCC or ``"1.2.3"`` for RVS) as capture group 1.
            ``None`` if this body's rulings aren't known to number paragraphs
            at all, in which case every section falls back to one whole-section
            chunk.
        section_headers: Ordered ``(markdown_header, section_label)`` pairs
            that define this body's Markdown section structure. Used by
            ``markdown_case.split_sections`` when ``dynamic_sections=False``.
            The ``markdown_header`` is the exact ``##``-prefixed string the
            body's own assemble step emits; ``section_label`` is the string
            stored in ``chunks.section`` and used as an HTML anchor on case
            pages. Ignored when ``dynamic_sections=True``.
        heading_category_map: Optional mapping from section keys to cross-court
            category strings (``CATEGORY_*`` constants). For fixed-section
            courts (``dynamic_sections=False``) keys are section labels (e.g.
            ``"facts"``); for dynamic-section courts (``dynamic_sections=True``)
            keys are verbatim heading texts as they appear in the body.
            Headings absent from the map get ``section_category=None``.
        dynamic_sections: When ``True``, ``markdown_case.split_sections``
            detects section boundaries by scanning for any ``## ``-prefixed
            line in the Markdown body (used for courts like RVS whose heading
            set is open-ended and varies per ruling). When ``False`` (default),
            splits on the fixed list in ``section_headers``.
    """

    key: str
    name: str
    paragraph_marker_re: re.Pattern[str] | None
    section_headers: tuple[tuple[str, str], ...] = field(default=())
    heading_category_map: dict[str, str] | None = field(default=None)
    dynamic_sections: bool = field(default=False)


# ---------------------------------------------------------------------------
# GHCC internals
# ---------------------------------------------------------------------------

# Sections are indicated by "<letter>.<number>", nesting arbitrarily deep
# (e.g. "B.7.", "B.76.2.3.") for "-A-" (party arguments) and "-B-"
# (Court's reasoning). Facts and operative-ruling have no numbering, so
# they fall back to a single whole-section chunk.
_GHCC_PARAGRAPH_MARKER_RE = re.compile(r"(?m)^\s*([A-Z](?:\.\d+)+)\.\s+")

# ---------------------------------------------------------------------------
# RVS internals
# ---------------------------------------------------------------------------

# RVS rulings number paragraphs with Arabic dot-notation: "1.", "1.2.",
# "1.2.3.", etc.
_RVS_PARAGRAPH_MARKER_RE = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*)\.\s+")

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SOURCES: dict[str, SourceConfig] = {
    SOURCE_CONSTITUTIONAL_COURT: SourceConfig(
        key=SOURCE_CONSTITUTIONAL_COURT,
        name="Grondwettelijk Hof (Cour Constitutionnelle)",
        paragraph_marker_re=_GHCC_PARAGRAPH_MARKER_RE,
        section_headers=(
            ("## Feiten en rechtspleging", GHCC_SECTION_FACTS),
            ("## Standpunten van de partijen", GHCC_SECTION_ARGUMENTS),
            ("## Beoordeling door het Hof", GHCC_SECTION_REASONING),
            ("## Beschikking", GHCC_SECTION_RULING),
        ),
        heading_category_map={
            GHCC_SECTION_FACTS: CATEGORY_FACTS,
            GHCC_SECTION_ARGUMENTS: CATEGORY_ARGUMENTS,
            GHCC_SECTION_REASONING: CATEGORY_REASONING,
            GHCC_SECTION_RULING: CATEGORY_OPERATIVE,
        },
    ),
    SOURCE_COUNCIL_OF_STATE: SourceConfig(
        key=SOURCE_COUNCIL_OF_STATE,
        name="Raad van State (Conseil d'État)",
        paragraph_marker_re=_RVS_PARAGRAPH_MARKER_RE,
        dynamic_sections=True,
        heading_category_map=_RVS_HEADING_CATEGORY_MAP,
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
