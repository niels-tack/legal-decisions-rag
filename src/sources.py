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
   ``paragraph_marker_re``, ``section_headers``, and ``heading_normalizer``.

Nothing in ``src.indexing.build_index``, ``src.markdown_case``, or
``src.query_service`` needs to change for either step - they read this
registry, not any specific body's hard-coded conventions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Grondwettelijk Hof / Constitutional Court (GHCC)
# ---------------------------------------------------------------------------

SOURCE_CONSTITUTIONAL_COURT = "GHCC"

# GHCC-specific section label constants. These strings are stored verbatim
# in the ``chunks.section`` column of ``cases.db`` and rendered as section
# anchors on case pages. The ingestion modules (``src.ingestion.extract``
# and ``src.ingestion.assemble``) import these rather than ``src.schemas``
# so the label definitions stay in one place alongside the rest of the
# GHCC configuration.
GHCC_SECTION_FACTS = "facts"
GHCC_SECTION_ARGUMENTS = "arguments"
GHCC_SECTION_REASONING = "reasoning"
GHCC_SECTION_RULING = "ruling"

# ---------------------------------------------------------------------------
# Raad van State / Council of State (RVS)
# ---------------------------------------------------------------------------

SOURCE_COUNCIL_OF_STATE = "RVS"

# RVS section label constants. These strings are stored verbatim in
# ``chunks.section`` and used as HTML anchors on case pages, just like
# the GHCC constants above.
#
# Design note: the RVS has a much richer heading hierarchy than the GHCC
# (admissibility, jurisdiction, suspension conditions, multiple examination
# tiers, etc.). Rather than collapsing everything to the GHCC's four labels,
# we keep RVS-specific labels so each body's structure is faithfully
# represented. The normalization map below (``RVS_HEADING_MAP``) is the
# single human-reviewed place where raw heading variants are mapped to these
# canonical labels.
RVS_SECTION_VOORWERP = "voorwerp"           # Subject / scope of the appeal
RVS_SECTION_FEITEN = "feiten"               # Facts
RVS_SECTION_STANDPUNT = "standpunt"         # Party standpoints / pleas
RVS_SECTION_ONTVANKELIJKHEID = "ontvankelijkheid"  # Admissibility
RVS_SECTION_RECHTSMACHT = "rechtsmacht"     # Jurisdiction
RVS_SECTION_SCHORSING = "schorsing"         # Suspension conditions
RVS_SECTION_MIDDELEN = "middelen"           # Examination of grounds (all tiers)
RVS_SECTION_BEOORDELING = "beoordeling"    # Court's assessment / operative part

# Human-reviewed normalization map: raw heading string as extracted from the
# source document → canonical ``##``-prefixed Markdown header written by the
# RVS assemble step. All variants that map to the same canonical header will
# end up under the same section label in ``cases.db``.
#
# Maintenance notes:
# - All keys are exact strings as they appear (or will appear after basic
#   cleaning) in the raw PDF/HTML text. Case-sensitive.
# - Add new variants here as they are discovered in the corpus; do not add
#   regex patterns (use the assemble step for fuzzy matching if needed).
# - The "standpunt" block is intentionally incomplete - the full variant list
#   must be expanded by reviewing the real RVS corpus before ingestion begins.
# - "Onderzoek van het Nde middel", sub-parts (onderdelen), and procedural
#   exceptions (excepties) all collapse to one "## Onderzoek van de middelen"
#   header so the indexer produces one searchable ``middelen`` section per
#   case regardless of how many individual grounds are examined.
RVS_HEADING_MAP: dict[str, str] = {
    # --- Voorwerp van het beroep ----------------------------------------
    "Voorwerp van de vordering": "## Voorwerp van het beroep",
    "Voorwerp van de beroepen": "## Voorwerp van het beroep",
    "Voorwerp van het beroep": "## Voorwerp van het beroep",
    # --- Feiten ---------------------------------------------------------
    "Feiten": "## Feiten",
    "De gegevens van de zaak": "## Feiten",
    # --- Standpunt van de partijen (INCOMPLETE - expand from corpus) ----
    "Standpunt van de partijen": "## Standpunt van de partijen",
    "Uiteenzetting van het middel": "## Standpunt van de partijen",
    "Betwisting door verzoekende partij": "## Standpunt van de partijen",
    # --- Ontvankelijkheid -----------------------------------------------
    "Ontvankelijkheid van het beroep": "## Ontvankelijkheid",
    "Ontvankelijkheid van de beroepen": "## Ontvankelijkheid",
    "Ontvankelijkheid van de vordering": "## Ontvankelijkheid",
    "De ontvankelijkheid": "## Ontvankelijkheid",
    "Ontvankelijkheid – belang": "## Ontvankelijkheid",   # en dash variant
    # --- Rechtsmacht ----------------------------------------------------
    "De rechtsmacht van de Raad van State": "## Rechtsmacht van de Raad van State",
    "Rechtsmacht van de Raad van State": "## Rechtsmacht van de Raad van State",
    "Exceptie betreffende de rechtsmacht": "## Rechtsmacht van de Raad van State",
    # --- Schorsingsvoorwaarden ------------------------------------------
    "Herinnering aan de schorsingsvoorwaarden": "## Schorsingsvoorwaarden",
    "Schorsingsvoorwaarden": "## Schorsingsvoorwaarden",
    "De schorsingsvoorwaarden": "## Schorsingsvoorwaarden",
    "De grondvoorwaarden voor de schorsing": "## Schorsingsvoorwaarden",
    # --- Onderzoek van de middelen (all examination tiers + excepties) --
    # Top-level "Onderzoek van" headings
    "Onderzoek van de middelen Enig middel": "## Onderzoek van de middelen",
    "Onderzoek van het eerste middel": "## Onderzoek van de middelen",
    "Onderzoek van het tweede middel": "## Onderzoek van de middelen",
    "Onderzoek van het derde middel": "## Onderzoek van de middelen",
    "Onderzoek van het vierde middel": "## Onderzoek van de middelen",
    "Onderzoek van het vijfde middel": "## Onderzoek van de middelen",
    "Onderzoek van het zesde middel": "## Onderzoek van de middelen",
    "Onderzoek van het zevende middel": "## Onderzoek van de middelen",
    # Individual ground labels (second tier)
    "Enig middel": "## Onderzoek van de middelen",
    "Eerste middel": "## Onderzoek van de middelen",
    "Tweede middel": "## Onderzoek van de middelen",
    "Derde middel": "## Onderzoek van de middelen",
    "Vierde middel": "## Onderzoek van de middelen",
    "Vijfde middel": "## Onderzoek van de middelen",
    "Zesde middel": "## Onderzoek van de middelen",
    # Sub-parts of grounds (third tier)
    "Eerste onderdeel": "## Onderzoek van de middelen",
    "Tweede onderdeel": "## Onderzoek van de middelen",
    "Derde onderdeel": "## Onderzoek van de middelen",
    "Vierde onderdeel": "## Onderzoek van de middelen",
    # Procedural exceptions (collapsed into middelen rather than a separate section
    # because they are substantive grounds examined alongside the main grounds)
    "Uiteenzetting van de exceptie": "## Onderzoek van de middelen",
    "Exceptie": "## Onderzoek van de middelen",
    "Excepties": "## Onderzoek van de middelen",
    "De exceptie": "## Onderzoek van de middelen",
    # --- Beoordeling ----------------------------------------------------
    "Beoordeling": "## Beoordeling",
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
            that define this body's Markdown section structure. The
            ``markdown_header`` is the exact ``##``-prefixed string the
            body's own assemble step emits (and ``markdown_case.split_sections``
            splits on); ``section_label`` is the free-form string stored in
            ``chunks.section`` and used as an HTML anchor on case pages.
            Order must match document order so ``split_sections`` can slice
            between consecutive headers correctly.
        heading_normalizer: Optional mapping from raw heading strings (as
            extracted from source PDFs/HTML) to the canonical ``##``-prefixed
            Markdown headers defined in ``section_headers``. Used by the
            body-specific assemble step to normalize heading variants before
            writing the ``.md`` file. ``None`` for bodies (like GHCC) whose
            rulings use a small, consistent set of headings that do not require
            normalization.
    """

    key: str
    name: str
    paragraph_marker_re: re.Pattern[str] | None
    section_headers: tuple[tuple[str, str], ...]
    heading_normalizer: dict[str, str] | None = field(default=None)


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
# "1.2.3.", etc. Roman-numeral headings (I., II., ...) mark major document
# sections and are handled by the normalization layer above, not as
# paragraph markers - they would produce misleadingly coarse chunks.
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
        heading_normalizer=None,
    ),
    SOURCE_COUNCIL_OF_STATE: SourceConfig(
        key=SOURCE_COUNCIL_OF_STATE,
        name="Raad van State (Conseil d'État)",
        paragraph_marker_re=_RVS_PARAGRAPH_MARKER_RE,
        section_headers=(
            ("## Voorwerp van het beroep", RVS_SECTION_VOORWERP),
            ("## Feiten", RVS_SECTION_FEITEN),
            ("## Standpunt van de partijen", RVS_SECTION_STANDPUNT),
            ("## Ontvankelijkheid", RVS_SECTION_ONTVANKELIJKHEID),
            ("## Rechtsmacht van de Raad van State", RVS_SECTION_RECHTSMACHT),
            ("## Schorsingsvoorwaarden", RVS_SECTION_SCHORSING),
            ("## Onderzoek van de middelen", RVS_SECTION_MIDDELEN),
            ("## Beoordeling", RVS_SECTION_BEOORDELING),
        ),
        heading_normalizer=RVS_HEADING_MAP,
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
