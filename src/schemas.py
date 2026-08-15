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
    """One numbered-paragraph chunk of a ruling's body text."""

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


class ChunkResult(BaseModel):
    """One matched chunk within a case search result."""

    section: str = Field(
        ...,
        description=(
            "Verbatim section heading or label. For GHCC this is a fixed label "
            "(e.g. 'reasoning'); for RVS it is the original heading text."
        ),
    )
    section_category: str | None = Field(
        None,
        description=(
            "Cross-court semantic category (e.g. 'facts', 'reasoning', 'operative'). "
            "None when the heading is not in the body's category map."
        ),
    )
    heading_level: int | None = Field(
        None,
        description=(
            "Depth of this section in the document heading hierarchy "
            "(1 = top-level, 2 = subsection, 3 = sub-subsection). "
            "None for headings not in the source's level map."
        ),
    )
    parent_heading: str | None = Field(
        None,
        description=(
            "Verbatim heading of the nearest ancestor section at a shallower level, "
            "or None if this is already a top-level section."
        ),
    )
    paragraph_number: str | None = Field(
        ..., description="This chunk's own numbered identifier, e.g. 'B.7.3'"
    )
    excerpt: str = Field(..., description="Truncated chunk text (response-size-capped)")
    score: float = Field(
        ..., description="Hybrid BM25 + vector reciprocal-rank-fusion score"
    )


class CaseSearchResult(BaseModel):
    """One ranked case with its top matching chunks. Cases are ranked by their 
    best chunk's score. Chunks within a case are ranked best-first by their own 
    scores.
    """

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
    source_pdf_url: str
    permalink_info_card: str | None = Field(
        None,
        description=(
            "Link to the court's information card for this ruling "
            "(e.g. https://nl.const-court.be/ARR/1/2025 for GHCC). "
            "None for courts that do not publish an information card."
        ),
    )
    best_score: float = Field(
        ..., description="Score of the highest-ranked matching chunk in this case"
    )
    chunks: list[ChunkResult] = Field(
        ..., description="Top matching chunks for this case, best-first"
    )


class SearchResponse(BaseModel):
    """Response body for ``GET /search``."""

    query: str
    results: list[CaseSearchResult]


