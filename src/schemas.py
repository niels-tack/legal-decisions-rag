"""Shared data contracts for the ingestion, indexing, and query-service modules.

Every module that produces or consumes case data (ingestion frontmatter,
the SQLite index builder, and the query service's search API) imports from
this module so the field names and shapes stay in sync across the pipeline.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CaseMetadata(BaseModel):
    """YAML frontmatter fields captured for one Constitutional Court ruling.

    The ECLI, arrest number, role number, and file slug are kept as separate
    fields because they are genuinely different identifiers in the source
    documents (e.g. ECLI ``ECLI:BE:GHCC:2025:ARR.001``, arrest number
    ``1/2025``, role number ``8115``, file slug ``2025-001n``); collapsing
    them into a single "case number" field risks citation errors.
    """

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
        ..., description="The law/article under constitutional review"
    )
    outcome: str = Field(
        ..., description="The Court's ruling outcome, e.g. 'Vernietiging'"
    )
    keywords: list[str] = Field(
        default_factory=list, description="Official Court subject keywords"
    )
    source_pdf_url: str = Field(..., description="URL of the original official PDF")
    title: str = Field(..., description="Short human-readable title for the ruling")


class Passage(BaseModel):
    """One chunk of a ruling's body text, scoped to a structural section."""

    case_id: int = Field(..., description="Foreign key into the cases table")
    section: str = Field(..., description="One of: facts, arguments, reasoning, ruling")
    text: str = Field(..., description="The passage's plain text content")


class SearchResultItem(BaseModel):
    """One ranked passage returned by the query service's search endpoint."""

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
