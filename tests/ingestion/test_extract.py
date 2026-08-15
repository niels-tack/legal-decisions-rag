"""Tests for src.ingestion.extract, exercised against the real sample PDF."""

from pathlib import Path

import pytest
from src.ingestion import extract
from src.sources import (
    GHCC_SECTION_ARGUMENTS,
    GHCC_SECTION_FACTS,
    GHCC_SECTION_REASONING,
    GHCC_SECTION_RULING,
)

SAMPLE_PDF_PATH = (
    Path(__file__).parents[2]
    / "reference"
    / "sample_decisions"
    / "CoC_pdf"
    / "2025-001n.pdf"
)


@pytest.fixture(scope="module")
def sample_sections() -> dict[str, str]:
    """Extract sections from the real sample ruling PDF once per test module."""
    return extract.extract_case_sections(SAMPLE_PDF_PATH)


@pytest.fixture(scope="module")
def sample_full_text() -> str:
    """Extract the cleaned, page-joined full text of the real sample ruling."""
    return extract.extract_pdf_text(SAMPLE_PDF_PATH)


def test_extract_ecli_finds_canonical_citation() -> None:
    """The ECLI should be read from the PDF's repeated footer line."""
    assert extract.extract_ecli(SAMPLE_PDF_PATH) == "ECLI:BE:GHCC:2025:ARR.001"


def test_extract_case_sections_finds_all_four_sections(
    sample_sections: dict[str, str],
) -> None:
    """Every one of the four structural sections should be found and non-empty."""
    for section in (
        GHCC_SECTION_FACTS,
        GHCC_SECTION_ARGUMENTS,
        GHCC_SECTION_REASONING,
        GHCC_SECTION_RULING,
    ):
        assert sample_sections[section].strip(), f"section {section!r} was empty"


def test_facts_section_starts_at_roman_numeral_heading(
    sample_sections: dict[str, str],
) -> None:
    """The facts section should start at the "I." heading, not mid-sentence."""
    assert sample_sections[GHCC_SECTION_FACTS].startswith("I.")


def test_arguments_section_starts_at_a_marker(sample_sections: dict[str, str]) -> None:
    """The party-arguments section should start at the "- A -" marker."""
    assert sample_sections[GHCC_SECTION_ARGUMENTS].startswith("- A -")


def test_reasoning_section_starts_at_b_marker(sample_sections: dict[str, str]) -> None:
    """The Court's-reasoning section should start at the "- B -" marker."""
    assert sample_sections[GHCC_SECTION_REASONING].startswith("- B -")


def test_ruling_section_contains_operative_formula(
    sample_sections: dict[str, str],
) -> None:
    """The ruling section should contain the standard "Om die redenen" formula."""
    assert "Om die redenen" in sample_sections[GHCC_SECTION_RULING]
    assert "zegt voor recht" in sample_sections[GHCC_SECTION_RULING]


def test_boilerplate_ecli_footer_does_not_leak_into_sections(
    sample_sections: dict[str, str],
) -> None:
    """The repeated ECLI footer line must not appear inside any section's text."""
    for section_text in sample_sections.values():
        assert "ECLI:BE:GHCC:2025:ARR.001" not in section_text


def test_masthead_does_not_leak_as_a_standalone_line(sample_full_text: str) -> None:
    """The bare "Grondwettelijk Hof" masthead line must be stripped from the text."""
    lines = [line.strip() for line in sample_full_text.split("\n")]
    assert "Grondwettelijk Hof" not in lines


def test_page_numbers_are_stripped_from_page_starts(sample_full_text: str) -> None:
    """Standalone page-number lines (e.g. a lone "2") must not remain in the text."""
    lines = [line.strip() for line in sample_full_text.split("\n")]
    # Pages 2 through 12 of the sample PDF each started with their own bare
    # page number before cleaning.
    for page_number in range(2, 13):
        assert str(page_number) not in lines


def test_split_into_sections_leaves_missing_marker_empty() -> None:
    """A marker that never appears should leave its section empty, not raise."""
    sections = extract.split_into_sections("just some unrelated text with no markers")

    assert sections[GHCC_SECTION_FACTS] == ""
    assert sections[GHCC_SECTION_ARGUMENTS] == ""
    assert sections[GHCC_SECTION_REASONING] == ""
    assert sections[GHCC_SECTION_RULING] == ""


def test_split_into_sections_tolerates_en_dash_marker_variant() -> None:
    """A "- B -" marker rendered with an en dash (a real one-off PDF-font quirk) still splits."""
    text = "I. Facts here\n- A -\nArguments here\n- B –\nReasoning here\nOm die redenen,\nRuling here"

    sections = extract.split_into_sections(text)

    assert sections[GHCC_SECTION_REASONING].startswith("- B")
    assert "Reasoning here" in sections[GHCC_SECTION_REASONING]
