"""Scrape the Constitutional Court's official Dutch-language case listing.

The live page (``https://www.const-court.be/nl/judgments?year=<year>``) is a
server-rendered Vuetify application: each ruling is a ``judgement-card`` div
carrying its date, procedure type, arrest number, PDF link, controlled norm,
outcome, role number(s), and keywords. This module was written against the
exact markup captured by a prior working scrape of that page (see
``reference/initial_version/extracting_information_from_website.ipynb`` and
the resulting records in ``reference/initial_version/overview.ipynb``); the
live site itself could not be re-fetched from this sandbox (see the
docstring on ``fetch_listing_html`` for why), so treat the selectors below as
"known good as of that prior scrape" rather than independently re-verified
today.

The network fetch (``fetch_listing_html``) and the HTML parsing
(``parse_listing_html``) are kept separate so the parser can be unit tested
against a saved fixture without any live HTTP call.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, TypedDict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Comment

BASE_URL = "https://www.const-court.be"
LISTING_URL_TEMPLATE = BASE_URL + "/nl/judgments?year={year}"

# The judgement-card class string observed live also carries Vuetify
# component classes (e.g. "judgement-card mx-auto my-4 v-card v-sheet
# theme--light"). BeautifulSoup's class_ matching checks membership in the
# element's parsed class list, so matching on this single class name is
# robust to the other classes' presence, order, or a future Vuetify bump.
_CARD_CLASS = "judgement-card"
_TOP_INFOS_CLASS = "top-infos"

_ROLE_NUMBER_PREFIX_RE = re.compile(r"^Rolnummers?\s*:?\s*", re.IGNORECASE)
_KEYWORDS_PREFIX_RE = re.compile(r"^Trefwoorden\s*:?\s*", re.IGNORECASE)


class DiscoveredRuling(TypedDict):
    """One ruling record scraped from the case overview listing.

    Deliberately excludes ``ecli``, ``file_slug``, and ``title``: the ECLI
    only appears inside the PDF itself, ``file_slug`` is derived from
    ``pdf_url`` by the caller, and ``title`` is synthesized by the pipeline
    from the fields captured here.
    """

    arrest_number: str
    role_number: str
    ruling_date: date
    procedure_type: str
    controlled_norm: str
    outcome: str
    keywords: list[str]
    pdf_url: str


def fetch_listing_html(
    year: int,
    language: str = "nl",
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> str:
    """Download the raw HTML of one year's case overview listing.

    Thin I/O wrapper, deliberately free of parsing logic, so tests can
    exercise ``parse_listing_html`` against a saved fixture instead of a
    live request.

    Args:
        year: Calendar year to fetch the listing for.
        language: Value sent in the ``Accept-Language`` header to request
            the Dutch-language version of the page.
        session: An existing ``requests.Session`` to reuse (e.g. the pipeline's
            polite session with retry/backoff configured). A throwaway
            session is created if omitted.
        timeout: Per-request timeout in seconds.

    Returns:
        The response body as text.

    Raises:
        requests.HTTPError: If the server returns a non-2xx status code.
    """
    http = session or requests.Session()
    response = http.get(
        LISTING_URL_TEMPLATE.format(year=year),
        headers={"Accept-Language": language},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def _parse_date(text: str) -> date:
    """Parse a ``dd/mm/yyyy`` date string as shown on the listing page.

    Args:
        text: The raw date text of one judgement card, e.g. ``"03/04/2025"``.

    Returns:
        The corresponding ``date``.
    """
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def _clean_role_number(text: str) -> str:
    """Normalize a role-number span's text into a single comma-joined string.

    The source text looks like ``"Rolnummer : 8115"`` or, for cases with
    multiple joined role numbers, ``"Rolnummers : 8224 - 8223"``.

    Args:
        text: The raw text of the role-number ``<span>``.

    Returns:
        The role number(s) joined with ``", "``, e.g. ``"8224, 8223"``.
    """
    stripped = _ROLE_NUMBER_PREFIX_RE.sub("", text).strip()
    parts = [part.strip() for part in stripped.split("-") if part.strip()]
    return ", ".join(parts)


def _clean_keywords(text: str) -> list[str]:
    """Normalize a keywords span's text into a list of individual keywords.

    Cases with no assigned keywords show a lone ``"-"`` on the site; that
    is treated as "no keywords" rather than a single literal keyword.

    Args:
        text: The raw text of the keywords ``<span>``, e.g.
            ``"Trefwoorden : Fiscaal recht - Registratierechten"``.

    Returns:
        A list of individual keyword strings, possibly empty.
    """
    stripped = _KEYWORDS_PREFIX_RE.sub("", text).strip()
    if not stripped or stripped == "-":
        return []
    return [part.strip() for part in stripped.split(" - ") if part.strip()]


def _extract_arrest_number(heading: Any) -> str:
    """Pull the arrest number out of a judgement card's ``<h3>`` heading.

    The heading contains an ``<a>`` (the PDF link, wrapping an icon/label)
    followed by a bare text node holding the arrest number, e.g.
    ``"61/2025"``. The prior working scraper located this text by finding
    the empty HTML comment ``<!-- -->`` that Vue's compiler leaves before
    it; the equivalent, more robust way with BeautifulSoup is to take the
    heading's direct text-node children (not the anchor's own text) while
    filtering out that same comment node.

    Args:
        heading: The ``<h3>`` tag of one judgement card.

    Returns:
        The arrest number text, e.g. ``"61/2025"``, or an empty string if
        the expected structure isn't found.
    """
    text_nodes = [
        node
        for node in heading.find_all(string=True, recursive=False)
        if not isinstance(node, Comment)
    ]
    return "".join(text_nodes).strip()


def parse_listing_html(html: str) -> list[DiscoveredRuling]:
    """Parse one year's case overview listing HTML into ruling records.

    Pure function: no network access, so this is fully unit-testable
    against a saved HTML fixture.

    Args:
        html: The raw HTML of a ``/nl/judgments?year=<year>`` page.

    Returns:
        One record per judgement card found, in document order. Cards
        missing an expected field yield an empty string/list for that
        field rather than raising, so a single malformed card doesn't
        abort the whole page.
    """
    soup = BeautifulSoup(html, "html.parser")
    rulings: list[DiscoveredRuling] = []

    for card in soup.find_all("div", class_=_CARD_CLASS):
        top_infos = card.find("div", class_=_TOP_INFOS_CLASS)
        paragraphs = top_infos.find_all("p") if top_infos is not None else []
        ruling_date = (
            _parse_date(paragraphs[0].get_text())
            if len(paragraphs) > 0
            else datetime.min.date()
        )
        procedure_type = (
            paragraphs[1].get_text(strip=True) if len(paragraphs) > 1 else ""
        )

        heading = card.find("h3")
        pdf_url = ""
        arrest_number = ""
        if heading is not None:
            anchor = heading.find("a")
            href = anchor.get("href") if anchor is not None else None
            if href:
                pdf_url = urljoin(BASE_URL, href)
            arrest_number = _extract_arrest_number(heading)

        role_number = ""
        keywords: list[str] = []
        remaining_spans: list[str] = []
        for span in card.find_all("span"):
            text = span.get_text(" ", strip=True)
            if _ROLE_NUMBER_PREFIX_RE.match(text):
                role_number = _clean_role_number(text)
            elif _KEYWORDS_PREFIX_RE.match(text):
                keywords = _clean_keywords(text)
            else:
                remaining_spans.append(text)

        controlled_norm = remaining_spans[0] if len(remaining_spans) > 0 else ""
        outcome = remaining_spans[1] if len(remaining_spans) > 1 else ""

        rulings.append(
            DiscoveredRuling(
                arrest_number=arrest_number,
                role_number=role_number,
                ruling_date=ruling_date,
                procedure_type=procedure_type,
                controlled_norm=controlled_norm,
                outcome=outcome,
                keywords=keywords,
                pdf_url=pdf_url,
            )
        )

    return rulings


def file_slug_from_pdf_url(pdf_url: str) -> str:
    """Derive the file/URL slug (e.g. ``"2025-001n"``) from a PDF URL.

    Args:
        pdf_url: The full PDF URL, e.g.
            ``"https://www.const-court.be/public/n/2025/2025-001n.pdf"``.

    Returns:
        The filename without its ``.pdf`` extension.

    Raises:
        ValueError: If ``pdf_url`` doesn't end in a recognizable filename.
    """
    match = re.search(r"([^/]+)\.pdf$", pdf_url, re.IGNORECASE)
    if match is None:
        raise ValueError(f"Could not derive a file slug from PDF URL: {pdf_url!r}")
    return match.group(1)
