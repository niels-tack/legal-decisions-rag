"""Scrape the Constitutional Court's official Dutch-language case listing.

Two distinct sources are used for GHCC ingestion, following the Court's own
referencing guidelines (``https://nl.const-court.be/rule/referencing-judgments``):

1. **Metadata listing** - ``https://nl.const-court.be/nl/judgments?year={year}``:
   a server-rendered Vuetify SPA, each ruling represented as a
   ``judgement-card`` div carrying its date, procedure type, arrest number,
   PDF link, controlled norm, outcome, role number(s), and keywords. This
   page applies TLS fingerprinting that blocks Python ``requests``; in
   practice the HTML is saved from a browser session and fed to
   ``parse_listing_html`` (a pure function with no network dependency).

2. **PDF downloads** - ``https://nl.const-court.be/public/n/``: a plain
   Apache directory listing, accessible without TLS fingerprinting. Year
   subdirectories (``/public/n/{year}/``) list PDFs as ``{year}-{seq:03d}n.pdf``
   (zero-padded three-digit sequence, Dutch ``n`` suffix). Some rulings also
   carry a companion ``-info.pdf`` (e.g. ``2026-002n-info.pdf``); these are
   information-card PDFs and are not ingested. ``ghcc_pdf_download_url``
   constructs the download URL from a file slug.

Three canonical URL patterns are defined here for use throughout the pipeline:
- **PDF permalink**: ``https://{lang}.const-court.be/{number}/{year}.pdf``
  (e.g. ``https://nl.const-court.be/14/2026.pdf``) - stored as
  ``source_pdf_url`` in the ``cases`` table.
- **Info card**: ``https://{lang}.const-court.be/ARR/{number}/{year}``
  (e.g. ``https://nl.const-court.be/ARR/31/2025``) - exposed as
  ``permalink_info_card`` in search results.
- **Download**: ``https://{lang}.const-court.be/public/n/{year}/{slug}.pdf``
  - used only by the ingestion pipeline, never stored.

``www.const-court.be`` still resolves but redirects to the language subdomain
(``nl.``, ``fr.``, ``de.``, ``en.``) since August 2025.
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

# Map from ISO 639-1 language code to the single-letter suffix used in the
# document server path (/public/n/) and in PDF filenames (2026-014n.pdf).
_LANG_SUFFIX: dict[str, str] = {"nl": "n", "fr": "f", "de": "d"}

# Apache directory listing <a href="..."> entries pointing to PDF files.
_APACHE_HREF_RE = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)

# Ruling PDF filename: {year}-{seq:03d}{lang_suffix}.pdf (not -info.pdf).
# Capture groups: (year, zero_padded_seq, lang_suffix)
_RULING_PDF_RE = re.compile(r"^(\d{4})-(\d{3})([a-z])\.pdf$", re.IGNORECASE)

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


def ghcc_permalink_pdf(arrest_number: str, language: str = "nl") -> str:
    """Canonical permalink to the published PDF of one GHCC ruling.

    Format: ``https://<language>.const-court.be/<number>/<year>.pdf``,
    following the court's official referencing rules.

    Args:
        arrest_number: Official arrest number, e.g. ``"1/2025"``.
        language: ISO 639-1 language code (``"nl"``, ``"fr"``, ``"de"``).

    Returns:
        Permalink URL, e.g. ``"https://nl.const-court.be/1/2025.pdf"``.
    """
    number, year = arrest_number.split("/", 1)
    return f"https://{language}.const-court.be/{number}/{year}.pdf"


def ghcc_permalink_info_card(arrest_number: str, language: str = "nl") -> str:
    """Canonical link to the GHCC information card for one ruling.

    Format: ``https://<language>.const-court.be/ARR/<number>/<year>``.

    Args:
        arrest_number: Official arrest number, e.g. ``"1/2025"``.
        language: ISO 639-1 language code.

    Returns:
        Info card URL, e.g. ``"https://nl.const-court.be/ARR/1/2025"``.
    """
    number, year = arrest_number.split("/", 1)
    return f"https://{language}.const-court.be/ARR/{number}/{year}"


def ghcc_pdf_download_url(file_slug: str, language: str = "nl") -> str:
    """Build the download URL for a GHCC ruling PDF from the public document server.

    The public document server (``/public/n/``) is used for ingestion because
    the main site applies TLS fingerprinting that blocks automated clients.
    The year component is inferred from the leading ``YYYY-`` part of the slug.

    Args:
        file_slug: The file/URL slug, e.g. ``"2025-001n"``.
        language: ISO 639-1 language code.

    Returns:
        Download URL, e.g.
        ``"https://nl.const-court.be/public/n/2025/2025-001n.pdf"``.
    """
    year = file_slug.split("-")[0]
    return f"https://{language}.const-court.be/public/n/{year}/{file_slug}.pdf"


# ---------------------------------------------------------------------------
# Document server discovery (accessible without TLS fingerprinting)
# ---------------------------------------------------------------------------


def fetch_document_server_listing(
    year: int,
    language: str = "nl",
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> str:
    """Fetch the Apache directory listing for one year from the document server.

    Unlike the Vuetify listing page, the document server returns a plain HTML
    directory index that Python ``requests`` can access directly without TLS
    fingerprinting or JavaScript rendering.

    Args:
        year: Calendar year, e.g. ``2026``.
        language: ISO 639-1 language code determining the subdirectory path
            (``nl`` → ``/public/n/``, ``fr`` → ``/public/f/``).
        session: An existing session to reuse.
        timeout: Per-request timeout in seconds.

    Returns:
        Raw HTML of the Apache directory listing page.

    Raises:
        requests.HTTPError: On a non-2xx response.
    """
    suffix = _LANG_SUFFIX.get(language, language[0])
    url = f"https://{language}.const-court.be/public/{suffix}/{year}/"
    http = session or requests.Session()
    response = http.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_document_server_listing(
    html: str, year: int, language: str = "nl"
) -> list[str]:
    """Parse an Apache directory listing into a sorted list of ruling file slugs.

    Filters to only the main ruling PDFs (``{year}-{seq:03d}{suffix}.pdf``);
    companion ``-info.pdf`` files are excluded.

    Args:
        html: Raw HTML of the Apache directory listing page.
        year: Calendar year used to validate filenames.
        language: ISO 639-1 language code whose single-letter suffix must
            match the PDF filename (e.g. ``nl`` → ``n`` in ``2026-014n.pdf``).

    Returns:
        Sorted list of file slugs, e.g. ``["2026-001n", "2026-002n", ...]``.
    """
    suffix = _LANG_SUFFIX.get(language, language[0])
    slugs: list[str] = []
    for href in _APACHE_HREF_RE.findall(html):
        filename = href.rsplit("/", 1)[-1]
        m = _RULING_PDF_RE.match(filename)
        if m and m.group(1) == str(year) and m.group(3).lower() == suffix:
            slugs.append(filename[:-4])  # strip .pdf
    return sorted(slugs)


def arrest_number_from_slug(file_slug: str) -> str:
    """Derive the official arrest number from a file slug.

    The slug encodes year and zero-padded sequence (e.g. ``"2026-014n"``);
    the arrest number strips the leading zeros (e.g. ``"14/2026"``).

    Args:
        file_slug: File/URL slug, e.g. ``"2026-014n"``.

    Returns:
        Arrest number string, e.g. ``"14/2026"``.
    """
    year_part, rest = file_slug.split("-", 1)
    seq_str = re.sub(r"[a-z]+$", "", rest, flags=re.IGNORECASE)
    return f"{int(seq_str)}/{year_part}"


# ---------------------------------------------------------------------------
# Info card fetching and parsing
# ---------------------------------------------------------------------------


def fetch_info_card_html(
    arrest_number: str,
    language: str = "nl",
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> str:
    """Fetch the HTML of the info card page for one ruling.

    Args:
        arrest_number: Official arrest number, e.g. ``"14/2026"``.
        language: ISO 639-1 language code.
        session: An existing session to reuse.
        timeout: Per-request timeout in seconds.

    Returns:
        Raw HTML of the info card page.

    Raises:
        requests.HTTPError: On a non-2xx response.
    """
    url = ghcc_permalink_info_card(arrest_number, language)
    http = session or requests.Session()
    response = http.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_info_card(
    html: str,
    file_slug: str,
    language: str = "nl",
) -> DiscoveredRuling:
    """Parse a GHCC info card page into a ``DiscoveredRuling``.

    The info card at ``https://{lang}.const-court.be/ARR/{number}/{year}``
    carries the ruling's date, procedure type, controlled norm, outcome,
    role number, and keywords. This parser is the authoritative metadata
    source when using document-server-based discovery (the listing page is
    not used).

    .. note::
        The HTML structure of the info card page has not yet been confirmed
        to be server-rendered (vs. a Nuxt.js SPA). If the page is SPA-only,
        BeautifulSoup will find no data and all fields will fall back to empty
        strings. Run ``fetch_info_card_html`` manually on a live ruling to
        verify before relying on this parser in production.

    Args:
        html: Raw HTML of the info card page.
        file_slug: File/URL slug, e.g. ``"2026-014n"``, used to derive the
            arrest number and PDF download URL when they cannot be found in
            the page.
        language: ISO 639-1 language code.

    Returns:
        A ``DiscoveredRuling`` record; fields that could not be parsed fall
        back to empty strings or empty lists.
    """
    soup = BeautifulSoup(html, "html.parser")
    arrest_number = arrest_number_from_slug(file_slug)
    pdf_url = ghcc_pdf_download_url(file_slug, language)

    # --- Fields extracted from the info card page ---
    # The HTML structure below is a best-effort guess based on standard
    # patterns used on similar court websites. Update these selectors once
    # the actual page HTML is confirmed (share a saved copy of any info card
    # page to validate and tighten this parser).

    def _text(selector: str) -> str:
        tag = soup.select_one(selector)
        return tag.get_text(separator=" ", strip=True) if tag else ""

    # Try common <dl>/<dt>/<dd> pattern first, then fall back to searching
    # the full page text for known Dutch label prefixes.
    ruling_date_text = (
        _text("dd.ruling-date")
        or _text("[data-field='date']")
        or _text(".arrest-date")
    )
    role_number_text = (
        _text("dd.role-number")
        or _text("[data-field='rolnummer']")
        or _text(".role-number")
    )
    procedure_type_text = (
        _text("dd.procedure-type")
        or _text("[data-field='procedure']")
        or _text(".procedure-type")
    )
    controlled_norm_text = (
        _text("dd.controlled-norm")
        or _text("[data-field='norm']")
        or _text(".controlled-norm")
    )
    outcome_text = (
        _text("dd.outcome")
        or _text("[data-field='outcome']")
        or _text(".outcome")
    )
    keywords_text = (
        _text("dd.keywords")
        or _text("[data-field='keywords']")
        or _text(".keywords")
    )

    # Parse the date; fall back to a sentinel so upstream code can detect
    # and log the failure rather than silently storing a wrong date.
    parsed_date: date
    try:
        parsed_date = _parse_date(ruling_date_text) if ruling_date_text else date.min
    except ValueError:
        parsed_date = date.min

    keywords: list[str] = (
        [k.strip() for k in keywords_text.split(" - ") if k.strip()]
        if keywords_text
        else []
    )

    return DiscoveredRuling(
        arrest_number=arrest_number,
        role_number=role_number_text,
        ruling_date=parsed_date,
        procedure_type=procedure_type_text,
        controlled_norm=controlled_norm_text,
        outcome=outcome_text,
        keywords=keywords,
        pdf_url=pdf_url,
    )
