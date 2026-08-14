"""Tests for src.ingestion.assemble's Markdown rendering and file writing."""

from datetime import date
from pathlib import Path

import yaml
from src.ingestion import assemble
from src.schemas import CaseMetadata
from src.sources import (
    GHCC_SECTION_ARGUMENTS,
    GHCC_SECTION_FACTS,
    GHCC_SECTION_REASONING,
    GHCC_SECTION_RULING,
)

SAMPLE_METADATA = CaseMetadata(
    source="GHCC",
    ecli="ECLI:BE:GHCC:2025:ARR.001",
    arrest_number="1/2025",
    role_number="8115",
    file_slug="2025-001n",
    ruling_date=date(2025, 1, 9),
    language="nl",
    procedure_type="Prejudiciële vraag",
    controlled_norm="Artikel 1 van de wet van 19 juli 1991",
    outcome="Geen antwoord vereist",
    keywords=["Bevolkingsregister", "Referentieadres"],
    source_pdf_url="https://www.const-court.be/public/n/2025/2025-001n.pdf",
    title="Prejudiciële vraag - Artikel 1 van de wet van 19 juli 1991",
)

SAMPLE_SECTIONS = {
    GHCC_SECTION_FACTS: "I. Onderwerp en rechtspleging.\n\nDe feiten worden uiteengezet.",
    GHCC_SECTION_ARGUMENTS: "- A -\n\nDe partijen voeren het volgende aan.",
    GHCC_SECTION_REASONING: "- B -\n\nHet Hof oordeelt als volgt.",
    GHCC_SECTION_RULING: "Om die redenen, het Hof zegt voor recht.",
}


def test_render_markdown_includes_exact_section_headers_in_order() -> None:
    """The four ##-headed sections must use the exact strings the indexer splits on."""
    markdown = assemble.render_markdown(SAMPLE_METADATA, SAMPLE_SECTIONS)

    expected_headers = [
        "## Feiten en rechtspleging",
        "## Standpunten van de partijen",
        "## Beoordeling door het Hof",
        "## Beschikking",
    ]
    positions = [markdown.index(header) for header in expected_headers]

    assert positions == sorted(positions)


def test_render_markdown_includes_section_body_text() -> None:
    """Each section's body text should appear under its header."""
    markdown = assemble.render_markdown(SAMPLE_METADATA, SAMPLE_SECTIONS)

    assert "De feiten worden uiteengezet." in markdown
    assert "De partijen voeren het volgende aan." in markdown
    assert "Het Hof oordeelt als volgt." in markdown
    assert "Om die redenen, het Hof zegt voor recht." in markdown


def test_render_markdown_frontmatter_round_trips_through_yaml() -> None:
    """Writing then re-parsing the frontmatter with yaml.safe_load must recover the fields."""
    markdown = assemble.render_markdown(SAMPLE_METADATA, SAMPLE_SECTIONS)

    assert markdown.startswith("---\n")
    _, frontmatter_yaml, _ = markdown.split("---\n", 2)
    parsed = yaml.safe_load(frontmatter_yaml)

    assert parsed["ecli"] == SAMPLE_METADATA.ecli
    assert parsed["arrest_number"] == SAMPLE_METADATA.arrest_number
    assert parsed["role_number"] == SAMPLE_METADATA.role_number
    assert parsed["file_slug"] == SAMPLE_METADATA.file_slug
    assert parsed["ruling_date"] == SAMPLE_METADATA.ruling_date
    assert parsed["language"] == SAMPLE_METADATA.language
    assert parsed["procedure_type"] == SAMPLE_METADATA.procedure_type
    assert parsed["controlled_norm"] == SAMPLE_METADATA.controlled_norm
    assert parsed["outcome"] == SAMPLE_METADATA.outcome
    assert parsed["keywords"] == SAMPLE_METADATA.keywords
    assert parsed["source_pdf_url"] == SAMPLE_METADATA.source_pdf_url
    assert parsed["title"] == SAMPLE_METADATA.title

    # And the round-tripped mapping should re-validate as a CaseMetadata.
    assert CaseMetadata.model_validate(parsed) == SAMPLE_METADATA


def test_render_markdown_missing_section_yields_empty_but_present_header() -> None:
    """A missing section should still get its header, with an empty body."""
    sections_without_ruling = {
        key: value for key, value in SAMPLE_SECTIONS.items() if key != GHCC_SECTION_RULING
    }

    markdown = assemble.render_markdown(SAMPLE_METADATA, sections_without_ruling)

    assert "## Beschikking" in markdown


def test_write_case_file_writes_to_file_slug_named_file(tmp_path: Path) -> None:
    """The written file's name should be exactly "<file_slug>.md"."""
    output_path = assemble.write_case_file(tmp_path, SAMPLE_METADATA, SAMPLE_SECTIONS)

    assert output_path == tmp_path / "2025-001n.md"
    assert output_path.is_file()


def test_write_case_file_creates_output_directory(tmp_path: Path) -> None:
    """write_case_file should create the output directory if it doesn't exist yet."""
    nested_dir = tmp_path / "Constitutional_Court_Belgium" / "NL"

    output_path = assemble.write_case_file(nested_dir, SAMPLE_METADATA, SAMPLE_SECTIONS)

    assert output_path.is_file()
    assert output_path.read_text(encoding="utf-8").startswith("---\n")


def test_write_case_file_content_matches_render_markdown(tmp_path: Path) -> None:
    """The file's contents should exactly match render_markdown's output."""
    output_path = assemble.write_case_file(tmp_path, SAMPLE_METADATA, SAMPLE_SECTIONS)

    assert output_path.read_text(encoding="utf-8") == assemble.render_markdown(
        SAMPLE_METADATA, SAMPLE_SECTIONS
    )
