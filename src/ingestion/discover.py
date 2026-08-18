"""Scrape the Constitutional Court's official case listing and document server.

Two distinct sources are used for GHCC ingestion:

1. **Metadata listing** - ``https://{lang}.const-court.be/judgments?year={year}``:
   A server-rendered Nuxt 3 app. Each ruling is a ``judgment-card`` div
   (``data-testid="judgment-card"``, ``id="arr-{seq}-{year}"``) carrying its
   date, procedure type, arrest number, controlled norm, outcome, role
   number(s), and keywords. This page is accessible without TLS
   fingerprinting from Python ``requests``.

2. **PDF downloads** - ``https://{lang}.const-court.be/public/{suffix}/{year}/``:
   A plain Apache directory listing, also accessible without TLS
   fingerprinting. Year subdirectories list PDFs as ``{year}-{seq:03d}{suffix}.pdf``
   (zero-padded three-digit sequence). Companion ``-info.pdf`` press-release
   files are excluded. ``ghcc_pdf_download_url`` constructs the download URL
   from a file slug.

Three canonical URL patterns are defined here for use throughout the pipeline:
- **PDF permalink**: ``https://{lang}.const-court.be/{number}/{year}.pdf``
  (e.g. ``https://nl.const-court.be/14/2026.pdf``) - stored as
  ``source_pdf_url`` in the ``cases`` table.
- **Info card**: ``https://{lang}.const-court.be/ARR/{number}/{year}``
  (e.g. ``https://nl.const-court.be/ARR/31/2025``) - exposed as
  ``permalink_info_card`` in search results.
- **Download**: ``https://{lang}.const-court.be/public/{suffix}/{year}/{slug}.pdf``
  - used only by the ingestion pipeline, never stored.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TypedDict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.const-court.be"
LISTING_URL_TEMPLATE = "https://{language}.const-court.be/judgments?year={year}"

# Map from ISO 639-1 language code to the single-letter suffix used in the
# document server path (/public/n/) and in PDF filenames (2026-014n.pdf).
_LANG_SUFFIX: dict[str, str] = {"nl": "n", "fr": "f", "de": "d"}

# Apache directory listing <a href="..."> entries pointing to PDF files.
_APACHE_HREF_RE = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)

# Ruling PDF filename: {year}-{seq:03d}{lang_suffix}.pdf (not -info.pdf).
# Capture groups: (year, zero_padded_seq, lang_suffix)
_RULING_PDF_RE = re.compile(r"^(\d{4})-(\d{3})([a-z])\.pdf$", re.IGNORECASE)

# Judgment card id attribute: arr-{seq}-{year}
_CARD_ID_RE = re.compile(r"^arr-(\d+)-(\d{4})$")

_ROLE_NUMBER_PREFIX_RE = re.compile(r"^Rolnummers?\s*:?\s*", re.IGNORECASE)
_KEYWORDS_PREFIX_RE = re.compile(r"^Trefwoorden\s*:?\s*", re.IGNORECASE)

# Tags that carry a single "Label : value" text node on the Court site.
_INLINE_TAGS = frozenset({"span", "p", "li"})

# Dutch label variants for each metadata field on the ARR info-card page.
_LABEL_DATE = ("Datum", "Datum arrest", "Datum uitspraak", "Beslist op")
_LABEL_ROLE = ("Rolnummer", "Rolnummers", "Rolnr")
_LABEL_PROCEDURE = (
    "Aard van de rechtspleging",
    "Type procedure",
    "Procedure",
    "Rechtspleging",
)
_LABEL_NORM = ("Bestreden bepaling", "Getoetste norm", "Norm", "Onderwerp")
_LABEL_OUTCOME = ("Dictum", "Uitspraak", "Beslissing", "Besluit")
_LABEL_KEYWORDS = ("Trefwoorden", "Sleutelwoorden", "Onderwerpen")


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
        language: ISO 639-1 language code; determines the subdomain
            (``nl.const-court.be``, ``fr.const-court.be``, etc.).
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
    url = LISTING_URL_TEMPLATE.format(language=language, year=year)
    response = http.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def _parse_date(text: str) -> date:
    """Parse a ``dd/mm/yyyy`` date string as shown on the listing page.

    Args:
        text: The raw date text of one judgment card, e.g. ``"03/04/2025"``.

    Returns:
        The corresponding ``date``.
    """
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def _clean_role_number(text: str) -> str:
    """Normalize a role-number element's text into a single comma-joined string.

    Handles both "Rolnummer: 8115" and "Rolnummer : 8115" formats, as well
    as plural multi-number forms like "Rolnummer: 8224 - 8223".

    Args:
        text: The raw text of the role-number element.

    Returns:
        The role number(s) joined with ``", "``, e.g. ``"8224, 8223"``.
    """
    stripped = _ROLE_NUMBER_PREFIX_RE.sub("", text).strip()
    parts = [part.strip() for part in stripped.split("-") if part.strip()]
    return ", ".join(parts)


def _clean_keywords(text: str) -> list[str]:
    """Normalize a keywords element's text into a list of individual keywords.

    A lone ``"-"`` is treated as "no keywords". The input may or may not
    carry a ``"Trefwoorden: "`` prefix.

    Args:
        text: The raw keywords text, e.g.
            ``"Leefmilieu - Waterbeleid - Bemesting"``.

    Returns:
        A list of individual keyword strings, possibly empty.
    """
    stripped = _KEYWORDS_PREFIX_RE.sub("", text).strip()
    if not stripped or stripped == "-":
        return []
    return [part.strip() for part in stripped.split(" - ") if part.strip()]


def parse_listing_html(html: str, language: str = "nl") -> list[DiscoveredRuling]:
    """Parse one year's case overview listing HTML into ruling records.

    Pure function: no network access, so this is fully unit-testable
    against a saved HTML fixture.

    Parses the Nuxt 3 SSR HTML returned by
    ``https://{lang}.const-court.be/judgments?year={year}``. Each judgment
    card has ``data-testid="judgment-card"`` and ``id="arr-{seq}-{year}"``;
    the file slug and download URL are derived from the card id.

    Args:
        html: The raw HTML of the listing page.
        language: ISO 639-1 language code used to derive file slugs
            (e.g. ``"nl"`` → suffix ``"n"`` → ``"2026-092n"``).

    Returns:
        One record per judgment card found, in document order. Cards
        missing an expected field yield an empty string/list for that
        field rather than raising, so a single malformed card doesn't
        abort the whole page.
    """
    soup = BeautifulSoup(html, "html.parser")
    rulings: list[DiscoveredRuling] = []
    suffix = _LANG_SUFFIX.get(language, language[0])

    for card in soup.find_all("div", attrs={"data-testid": "judgment-card"}):
        # Derive arrest number and file slug from the card id (e.g. "arr-92-2026").
        card_id = str(card.get("id", ""))
        id_match = _CARD_ID_RE.match(card_id)
        if id_match is None:
            continue
        seq = int(id_match.group(1))
        year_str = id_match.group(2)
        file_slug = f"{year_str}-{seq:03d}{suffix}"
        arrest_number = f"{seq}/{year_str}"
        pdf_url = ghcc_pdf_download_url(file_slug, language)

        # Date: first span.text-body-medium in the card.
        date_span = card.find("span", class_="text-body-medium")
        try:
            ruling_date = (
                _parse_date(date_span.get_text(strip=True)) if date_span else date.min
            )
        except ValueError:
            ruling_date = date.min

        # Procedure type: span with BOTH text-body-medium AND ml-auto classes.
        # Uses CSS selector because BS4's class_ list argument is OR, not AND.
        procedure_span = card.select_one("span.text-body-medium.ml-auto")
        procedure_type = procedure_span.get_text(strip=True) if procedure_span else ""

        # Controlled norm: first div.mt-2 (contains the law/article under review).
        norm_div = card.find("div", class_="mt-2")
        controlled_norm = norm_div.get_text(separator=" ", strip=True) if norm_div else ""

        # Outcome: div with the text-emphasis class (visually highlighted verdict).
        outcome_div = card.find("div", class_="text-emphasis")
        outcome = outcome_div.get_text(separator=" ", strip=True) if outcome_div else ""

        # Role number: first div.text-body-small whose text starts with "Rolnummer".
        role_number = ""
        for div in card.find_all("div", class_="text-body-small"):
            text = div.get_text(strip=True)
            if _ROLE_NUMBER_PREFIX_RE.match(text):
                role_number = _clean_role_number(text)
                break

        # Keywords: div.judgment-caption-text (dash-separated topic tags).
        keywords_div = card.find("div", class_="judgment-caption-text")
        keywords = (
            _clean_keywords(keywords_div.get_text(strip=True)) if keywords_div else []
        )

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
            ``"https://nl.const-court.be/public/n/2025/2025-001n.pdf"``.

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

    The public document server (``/public/{suffix}/``) is used for ingestion
    because it is accessible without TLS fingerprinting. The year component
    is inferred from the leading ``YYYY-`` part of the slug.

    Args:
        file_slug: The file/URL slug, e.g. ``"2025-001n"``.
        language: ISO 639-1 language code.

    Returns:
        Download URL, e.g.
        ``"https://nl.const-court.be/public/n/2025/2025-001n.pdf"``.
    """
    year = file_slug.split("-")[0]
    suffix = _LANG_SUFFIX.get(language, language[0])
    return f"https://{language}.const-court.be/public/{suffix}/{year}/{file_slug}.pdf"


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

    Unlike the listing page, the document server returns a plain HTML
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
# Info card fetching and parsing (kept for historical reference; the pipeline
# now uses parse_listing_html instead)
# ---------------------------------------------------------------------------


def _find_labeled_value(soup: BeautifulSoup, *labels: str) -> str:
    """Return the value paired with the first matching Dutch label.

    Searches two HTML patterns in order:

    1. ``<dt>label</dt><dd>value</dd>`` or ``<th>label</th><td>value</td>``:
       used by definition-list and table-based info pages.
    2. An inline element (``<span>``, ``<p>``, ``<li>``) whose full text
       matches ``"label : value"``: used by the Vuetify listing page and
       similar span-based info-card variants.

    Args:
        soup: Parsed HTML document.
        *labels: Dutch label strings to try, in order of preference.

    Returns:
        The extracted value text, or an empty string if nothing matched.
    """
    for label in labels:
        re_exact = re.compile(r"^\s*" + re.escape(label) + r"\s*$", re.IGNORECASE)

        # Pattern 1: definition list or table (<dt>/<th> → <dd>/<td>).
        for tag_name in ("dt", "th"):
            el = soup.find(tag_name, string=re_exact)
            if el is not None:
                sibling = el.find_next_sibling(["dd", "td"])
                if sibling is not None:
                    return sibling.get_text(separator=" ", strip=True)

        # Pattern 2: inline "label : value" element.
        re_prefix = re.compile(
            r"^\s*" + re.escape(label) + r"\s*:?\s*(.+)$", re.IGNORECASE
        )
        for el in soup.find_all(_INLINE_TAGS):
            text = el.get_text(" ", strip=True)
            m = re_prefix.match(text)
            if m:
                return m.group(1).strip()

    return ""


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

    Uses :func:`_find_labeled_value` to scan for Dutch label text in both
    ``<dt>/<dd>`` definition-list structure and inline ``"label : value"``
    spans.

    Args:
        html: Raw HTML of the info card page.
        file_slug: File/URL slug, e.g. ``"2026-014n"``, used to derive the
            arrest number and PDF download URL.
        language: ISO 639-1 language code.

    Returns:
        A ``DiscoveredRuling`` record; fields that could not be parsed fall
        back to empty strings or empty lists rather than raising.
    """
    soup = BeautifulSoup(html, "html.parser")
    arrest_number = arrest_number_from_slug(file_slug)
    pdf_url = ghcc_pdf_download_url(file_slug, language)

    ruling_date_text = _find_labeled_value(soup, *_LABEL_DATE)
    role_number_text = _find_labeled_value(soup, *_LABEL_ROLE)
    procedure_type_text = _find_labeled_value(soup, *_LABEL_PROCEDURE)
    controlled_norm_text = _find_labeled_value(soup, *_LABEL_NORM)
    outcome_text = _find_labeled_value(soup, *_LABEL_OUTCOME)
    keywords_text = _find_labeled_value(soup, *_LABEL_KEYWORDS)

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
