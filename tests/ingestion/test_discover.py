"""Tests for src.ingestion.discover's HTML parser (no live network access)."""

from datetime import date
from pathlib import Path

import pytest
from src.ingestion import discover

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "listing_sample.html"
INFO_CARD_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "info_card_sample.html"
REAL_SAMPLE_PATH = (
    Path(__file__).parents[2] / "reference" / "real_samples" / "listing_2026-07_nl.html"
)


@pytest.fixture
def listing_html() -> str:
    """Load the saved case-overview listing HTML fixture."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parse_listing_html_finds_all_cards(listing_html: str) -> None:
    """Every judgement-card in the fixture should yield one record."""
    rulings = discover.parse_listing_html(listing_html)

    assert len(rulings) == 3


def test_parse_listing_html_extracts_single_docket_number_case(
    listing_html: str,
) -> None:
    """The first card's fields should be parsed exactly as shown on the page."""
    rulings = discover.parse_listing_html(listing_html)
    first = rulings[0]

    assert first["case_number"] == "92/2026"
    assert first["docket_number"] == "8510"
    assert first["ruling_date"] == date(2026, 7, 16)
    assert first["procedure_type"] == "Beroep tot vernietiging"
    assert first["controlled_norm"] is not None
    assert first["outcome"] is not None
    assert "waterbeleid" in first["controlled_norm"].lower()
    assert "Verwerping" in first["outcome"]
    assert first["keywords"] == ["Leefmilieu", "Vlaams Gewest", "Waterbeleid"]
    assert first["pdf_url"] == "https://nl.const-court.be/public/n/2026/2026-092n.pdf"

    """A page with no judgement-card elements should yield an empty list."""
    rulings = discover.parse_listing_html("<html><body>No cases here.</body></html>")

    assert rulings == []


# ---------------------------------------------------------------------------
# Real-world sample (reference/real_samples/listing_2026-07_nl.html), captured
# from https://nl.const-court.be/judgments?year=2026&month=7. Grounds the
# parser against markup shapes the hand-written fixture above doesn't cover.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_listing_html() -> str:
    """Load the real captured listing HTML sample."""
    return REAL_SAMPLE_PATH.read_text(encoding="utf-8")


def test_parse_real_sample_finds_all_four_cards(real_listing_html: str) -> None:
    """All four complete cards in the real capture should be parsed."""
    rulings = discover.parse_listing_html(real_listing_html)

    assert [r["case_number"] for r in rulings] == [
        "92/2026",
        "91/2026",
        "90/2026",
        "89/2026",
    ]


def test_parse_real_sample_preserves_guillemets_in_controlled_norm(
    real_listing_html: str,
) -> None:
    """Guillemet-quoted law titles (« ... ») should come through unescaped."""
    rulings = discover.parse_listing_html(real_listing_html)

    assert rulings[0]["controlled_norm"] is not None
    assert "« tot wijziging van het decreet" in rulings[0]["controlled_norm"]


def test_parse_real_sample_joins_br_separated_outcome_bullets(
    real_listing_html: str,
) -> None:
    """A <br>-separated bulleted outcome (arr-89-2026) should join into one
    space-separated string, keeping each bullet's leading '-' intact."""
    rulings = discover.parse_listing_html(real_listing_html)
    outcome = rulings[3]["outcome"]
    assert outcome is not None

    assert outcome.startswith("- Prejudiciële vragen aan het Hof van Justitie")
    assert " - Vernietiging (artikel 51/5" in outcome
    assert "<br>" not in outcome


def test_parse_real_sample_dash_joined_docket_numbers(real_listing_html: str) -> None:
    """ "8411 - 8412" (arr-89-2026) should be split and comma-joined."""
    rulings = discover.parse_listing_html(real_listing_html)

    assert rulings[3]["docket_number"] == "8411, 8412"


def test_parse_real_sample_ignores_press_release_link(real_listing_html: str) -> None:
    """A "Persbericht" press-release link (arr-91-2026, arr-89-2026) must not
    be picked up as, or corrupt, the controlled norm or outcome fields."""
    rulings = discover.parse_listing_html(real_listing_html)

    assert rulings[1]["controlled_norm"] is not None
    assert rulings[1]["outcome"] is not None
    assert rulings[3]["outcome"] is not None
    assert "Persbericht" not in rulings[1]["controlled_norm"]
    assert "Persbericht" not in rulings[1]["outcome"]
    assert "Persbericht" not in rulings[3]["outcome"]


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
