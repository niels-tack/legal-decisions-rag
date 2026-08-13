"""Tests for src.ingestion.discover's HTML parser (no live network access)."""

from datetime import date
from pathlib import Path

import pytest
from src.ingestion import discover

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "listing_sample.html"


@pytest.fixture
def listing_html() -> str:
    """Load the saved case-overview listing HTML fixture."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parse_listing_html_finds_all_cards(listing_html: str) -> None:
    """Every judgement-card in the fixture should yield one record."""
    rulings = discover.parse_listing_html(listing_html)

    assert len(rulings) == 3


def test_parse_listing_html_extracts_single_role_number_case(listing_html: str) -> None:
    """The first card's fields should be parsed exactly as shown on the page."""
    rulings = discover.parse_listing_html(listing_html)
    first = rulings[0]

    assert first["arrest_number"] == "61/2025"
    assert first["role_number"] == "8423"
    assert first["ruling_date"] == date(2025, 4, 3)
    assert first["procedure_type"] == "Beroep tot vernietiging"
    assert (
        first["controlled_norm"]
        == "Wetten en procedures inzake gedeeltelijke verbeurdverklaring"
    )
    assert first["outcome"] == "Verwerping van het beroep"
    assert first["keywords"] == [
        "Voorafgaande rechtspleging",
        "Beroep tot vernietiging",
    ]
    assert first["pdf_url"] == "https://www.const-court.be/public/n/2025/2025-061n.pdf"


def test_parse_listing_html_joins_multiple_role_numbers(listing_html: str) -> None:
    """A case with several joined role numbers should have them comma-joined."""
    rulings = discover.parse_listing_html(listing_html)
    third = rulings[2]

    assert third["role_number"] == "8224, 8223"


def test_parse_listing_html_treats_bare_dash_keywords_as_empty(
    listing_html: str,
) -> None:
    """A "-" keywords value (no keywords assigned) should parse as an empty list."""
    rulings = discover.parse_listing_html(listing_html)
    third = rulings[2]

    assert third["keywords"] == []


def test_parse_listing_html_returns_empty_list_for_no_cards() -> None:
    """A page with no judgement-card elements should yield an empty list."""
    rulings = discover.parse_listing_html("<html><body>No cases here.</body></html>")

    assert rulings == []


@pytest.mark.parametrize(
    ("pdf_url", "expected_slug"),
    [
        ("https://www.const-court.be/public/n/2025/2025-061n.pdf", "2025-061n"),
        ("https://www.const-court.be/public/n/2025/2025-001n.PDF", "2025-001n"),
    ],
)
def test_file_slug_from_pdf_url(pdf_url: str, expected_slug: str) -> None:
    """The file slug should be the PDF filename without its extension."""
    assert discover.file_slug_from_pdf_url(pdf_url) == expected_slug


def test_file_slug_from_pdf_url_rejects_url_without_pdf_filename() -> None:
    """A URL with no recognizable PDF filename should raise, not silently fail."""
    with pytest.raises(ValueError, match="Could not derive a file slug"):
        discover.file_slug_from_pdf_url("https://www.const-court.be/nl/judgments")
