"""Tests for src.ingestion.discover's HTML parser (no live network access)."""

from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
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


def test_parse_listing_html_joins_multiple_docket_numbers(listing_html: str) -> None:
    """A case with several joined docket numbers should have them comma-joined."""
    rulings = discover.parse_listing_html(listing_html)
    third = rulings[2]

    expected_range = ", ".join(str(number) for number in range(8463, 8514))
    assert third["docket_number"] == expected_range


def test_clean_docket_number_expands_inclusive_range() -> None:
    """A multi-number docket range should expand to every number in between."""
    assert discover._clean_docket_number("Rolnummer: 8224 - 8226") == "8224, 8225, 8226"


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


# ---------------------------------------------------------------------------
# _find_labeled_value
# ---------------------------------------------------------------------------


def test_find_labeled_value_dl_pattern() -> None:
    """dt/dd pairs should be matched by their exact label text."""
    html = "<dl><dt>Datum</dt><dd>14/02/2026</dd></dl>"
    soup = BeautifulSoup(html, "html.parser")
    assert discover._find_labeled_value(soup, "Datum") == "14/02/2026"


def test_find_labeled_value_table_pattern() -> None:
    """th/td pairs should be matched when dl is absent."""
    html = "<table><tr><th>Dictum</th><td>Geen schending</td></tr></table>"
    soup = BeautifulSoup(html, "html.parser")
    assert discover._find_labeled_value(soup, "Dictum") == "Geen schending"


def test_find_labeled_value_inline_span_pattern() -> None:
    """Inline span 'Label : value' should be matched as the fallback."""
    html = "<span>Rolnummer : 9123</span>"
    soup = BeautifulSoup(html, "html.parser")
    assert discover._find_labeled_value(soup, "Rolnummer") == "9123"


def test_find_labeled_value_tries_labels_in_order() -> None:
    """The first matching label wins; remaining labels are not tried."""
    html = "<dl><dt>Dictum</dt><dd>Verwerping</dd></dl>"
    soup = BeautifulSoup(html, "html.parser")
    # "Uitspraak" is not present; "Dictum" is - should still return the value.
    assert discover._find_labeled_value(soup, "Uitspraak", "Dictum") == "Verwerping"


def test_find_labeled_value_returns_empty_when_absent() -> None:
    """A page with none of the given labels should return an empty string."""
    soup = BeautifulSoup(
        "<html><body><p>No metadata here.</p></body></html>", "html.parser"
    )
    assert discover._find_labeled_value(soup, "Datum", "Beslist op") == ""


# ---------------------------------------------------------------------------
# parse_info_card  (dl/dd fixture)
# ---------------------------------------------------------------------------


@pytest.fixture
def info_card_html() -> str:
    """Load the saved info card HTML fixture."""
    return INFO_CARD_FIXTURE_PATH.read_text(encoding="utf-8")


def test_parse_info_card_date(info_card_html: str) -> None:
    """The ruling date should be parsed from the Datum label."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["ruling_date"] == date(2026, 2, 14)


def test_parse_info_card_docket_number(info_card_html: str) -> None:
    """The docket number should be extracted from the Rolnummer label."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["docket_number"] == "9123"


def test_parse_info_card_procedure_type(info_card_html: str) -> None:
    """The procedure type should be extracted from the rechtspleging label."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["procedure_type"] == "Prejudiciële vraag"


def test_parse_info_card_splits_challenged_and_applied_norm(
    info_card_html: str,
) -> None:
    """Bestreden bepaling and Getoetste norm must remain distinct metadata."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["challenged_norm"] is not None
    assert "Vlaamse Wooncode" in ruling["challenged_norm"]
    assert ruling["applied_norm"] is None


def test_parse_info_card_extracts_both_norm_labels_when_present() -> None:
    """When both labels appear, each should be captured separately."""
    html = """
    <html><body>
      <dl>
        <dt>Bestreden bepaling</dt><dd>Decreet van 15 juli 1997 houdende de Vlaamse Wooncode (artikel 92)</dd>
        <dt>Getoetste norm</dt><dd>Artikel 4, eerste lid, van de Grondwet</dd>
      </dl>
    </body></html>
    """
    ruling = discover.parse_info_card(html, "2026-014n")
    assert ruling["challenged_norm"] is not None
    assert ruling["applied_norm"] is not None
    assert "Vlaamse Wooncode" in ruling["challenged_norm"]
    assert "Grondwet" in ruling["applied_norm"]


def test_parse_info_card_outcome(info_card_html: str) -> None:
    """The outcome should be extracted from the Dictum label."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["outcome"] == "Geen schending"


def test_parse_info_card_keywords(info_card_html: str) -> None:
    """Keywords should be split on ' - ' and returned as a list."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["keywords"] == ["Wonen", "Sociale huisvesting"]


def test_parse_info_card_derived_fields(info_card_html: str) -> None:
    """Case number and pdf_url are derived from the slug, not from the HTML."""
    ruling = discover.parse_info_card(info_card_html, "2026-014n")
    assert ruling["case_number"] == "14/2026"
    assert "2026-014n.pdf" in ruling["pdf_url"]


def test_parse_info_card_empty_page_falls_back_gracefully() -> None:
    """A page with no recognizable metadata should yield None values, not raise."""
    ruling = discover.parse_info_card("<html><body></body></html>", "2026-001n")
    assert ruling["procedure_type"] is None
    assert ruling["keywords"] == []
    assert ruling["ruling_date"] is None


def test_parse_info_card_inline_span_fallback() -> None:
    """span-based 'label : value' format should also be parsed correctly."""
    html = """
    <html><body>
      <span>Rolnummer : 8423</span>
      <span>Trefwoorden : Grondrechten - Eigendomsrecht</span>
    </body></html>
    """
    ruling = discover.parse_info_card(html, "2025-061n")
    assert ruling["docket_number"] == "8423"
    assert ruling["keywords"] == ["Grondrechten", "Eigendomsrecht"]
