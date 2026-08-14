"""Shared data contracts for the ingestion, indexing, and query-service modules.

Every module that produces or consumes case data (ingestion frontmatter,
the SQLite index builder, and the query service's search API) imports from
this module so the field names and shapes stay in sync across the pipeline.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CaseMetadata(BaseModel):
    """YAML frontmatter fields captured for one ruling."""

    source: str = Field(
        ...,
        description=(
            "Issuing judicial body, e.g. 'GHCC' for the Constitutional "
            "Court."
        ),
    )
    ecli: str = Field(
        ..., description="Canonical citation, e.g. ECLI:BE:GHCC:2025:ARR.001"
    )
    arrest_number: str = Field(..., description="Official arrest number, e.g. 1/2025")
    role_number: str = Field(
        ..., description="Role/docket number(s) ('rolnummer'), e.g. 8115"
    )
    file_slug: str = Field(
        ..., description="Source PDF filename without extension, e.g. 2025-001n"
    )
    ruling_date: date = Field(..., description="Date the ruling was rendered")
    language: str = Field(
        default="nl", description="ISO 639-1 language code of the ruling text"
    )
    procedure_type: str = Field(..., description="e.g. 'Prejudiciële vraag'")
    controlled_norm: str = Field(
        ..., description="The law/article under review"
    )
    outcome: str = Field(
        ..., description="The Court's ruling outcome, e.g. 'Vernietiging'"
    )
    keywords: list[str] = Field(
        default_factory=list, description="Official Court subject keywords"
    )
    source_pdf_url: str = Field(..., description="URL of the original official PDF")
    title: str = Field(..., description="Short human-readable title for the ruling")


class Chunk(BaseModel):
    """One numbered-paragraph chunk of a ruling's body text.

    Chunking happens at the paragraph-numbering granularity of the ruling's
    own body (e.g. ``B.7.3``), not at the coarser section granularity -
    ``section`` is retained purely as metadata. A section with no numbering
    (or a body with no numbering convention at all, see
    ``src.sources.SourceConfig.paragraph_marker_re``) falls back to a single
    whole-section chunk with ``paragraph_number=None``.
    """

    case_id: int = Field(..., description="Foreign key into the cases table")
    section: str = Field(..., description="One of: facts, arguments, reasoning, ruling")
    paragraph_number: str | None = Field(
        ..., description="This chunk's own numbered identifier, e.g. 'B.7.3'"
    )
    parent_numbers: list[str] = Field(
        default_factory=list,
        description="Ancestor identifiers, e.g. ['B', 'B.7'] for 'B.7.3'",
    )
    text: str = Field(..., description="The chunk's plain text content")


class SearchResultItem(BaseModel):
    """One ranked passage returned by the query service's search endpoint."""

    source: str = Field(..., description="Issuing judicial body, e.g. 'GHCC'")
    ecli: str
    arrest_number: str
    role_number: str
    case_number: str = Field(..., description="File/URL slug, e.g. 2025-001n")
    ruling_date: date
    language: str
    procedure_type: str
    controlled_norm: str
    outcome: str
    title: str
    section: str
    paragraph_number: str | None = Field(
        ..., description="The excerpt's own numbered identifier, e.g. 'B.7.3'"
    )
    excerpt: str
    source_pdf_url: str
    score: float = Field(
        ..., description="Hybrid BM25 + vector reciprocal-rank-fusion score"
    )


class SearchResponse(BaseModel):
    """Response body for ``GET /search``."""

    query: str
    results: list[SearchResultItem]


# Structural section labels used consistently by the Markdown assembler,
# the index builder's chunker, and any documentation referencing sections.
SECTION_FACTS = "facts"
SECTION_ARGUMENTS = "arguments"
SECTION_REASONING = "reasoning"
SECTION_RULING = "ruling"
KNOWN_SECTIONS = (SECTION_FACTS, SECTION_ARGUMENTS, SECTION_REASONING, SECTION_RULING)
