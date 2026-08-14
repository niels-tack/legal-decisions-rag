"""Extract clean, structured text from a Constitutional Court ruling PDF.

Text is pulled per page with ``pdfplumber``'s built-in ``extract_text()``.
Repeated header/footer boilerplate is
stripped per page via regex before the pages are joined, and the resulting
full text is split into the four structural sections shared via
``src.schemas`` using the rulings' own consistent section markers.

Marker patterns and the boilerplate layout below were derived by inspecting
``reference/sample_decisions/CoC_pdf/2025-001n.pdf`` directly with
pdfplumber.
"""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from src.sources import (
    GHCC_SECTION_ARGUMENTS,
    GHCC_SECTION_FACTS,
    GHCC_SECTION_REASONING,
    GHCC_SECTION_RULING,
)

# Observed per page of the sample ruling:
#   - every page's final line is the repeated ECLI footer, e.g.
#     "ECLI:BE:GHCC:2025:ARR.001";
#   - every page after the first starts with a bare page-number line;
#   - the "Grondwettelijk Hof" masthead appears as its own line on page 1.
# The masthead check below runs on every page regardless, since nothing
# guarantees only page 1 carries it across the full corpus.
_FOOTER_ECLI_RE = re.compile(r"^ECLI:BE:GHCC:\d{4}:ARR\.\d+\s*$")
_MASTHEAD_RE = re.compile(r"^Grondwettelijk Hof\s*$")
_PAGE_NUMBER_RE = re.compile(r"^\d{1,4}\s*$")

# The ECLI also lives in that same repeated footer line, which is the most
# reliable place to read it back out of *before* it gets stripped below.
ECLI_RE = re.compile(r"ECLI:BE:GHCC:\d{4}:ARR\.\d+")

# "I." heading starting the facts/procedure section. Anchored to the start
# of a line and requiring a capital letter after the whitespace that
# follows "I." so it reads as a heading (e.g. "I.  Onderwerp ...") rather
# than, say, a mid-sentence reference to "I. " in running text. The literal
# "I\." (not just "I") also naturally excludes "II.", "III.", etc.
_FACTS_MARKER_RE = re.compile(r"(?m)^\s*I\.\s+[A-ZÀ-ÖØ-Þ]")

# "- A -" / "- B -" party-arguments and reasoning markers, each on their
# own line. The dash character class covers a real one-off observed in the
# sample corpus (2025-004n.pdf), whose closing "- B -" marker renders with
# an en dash (U+2013) instead of a plain hyphen - almost certainly a
# font-subset quirk of that particular source file rather than a
# deliberate choice, but cheap to tolerate.
_DASH = "-‐‑‒–—−"
_ARGUMENTS_MARKER_RE = re.compile(rf"(?m)^\s*[{_DASH}]\s*A\s*[{_DASH}]\s*$")
_REASONING_MARKER_RE = re.compile(rf"(?m)^\s*[{_DASH}]\s*B\s*[{_DASH}]\s*$")

# Operative-ruling markers, tried in order: the standard "Om die redenen"
# formula is by far the most reliable; "het Hof" and "zegt voor recht" are
# fallbacks for the rare ruling where that exact phrase is absent.
_RULING_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?mi)^\s*Om die redenen\b"),
    re.compile(r"(?mi)^\s*het Hof\s*$"),
    re.compile(r"(?i)zegt voor recht"),
)


def _clean_page_text(raw_text: str, is_first_page: bool) -> str:
    """Strip repeated header/footer boilerplate from one page's raw text.

    Applied per page, before pages are joined, per the project's decision
    to use regex pattern matching rather than coordinate-based cropping.

    Args:
        raw_text: The page's ``extract_text()`` output (may be empty).
        is_first_page: Whether this is the document's first page. The
            page-number line is only stripped on later pages, since page 1
            is unnumbered in the source PDFs.

    Returns:
        The page text with boilerplate lines removed.
    """
    lines = raw_text.split("\n")
    cleaned_lines: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _FOOTER_ECLI_RE.match(stripped):
            continue
        if _MASTHEAD_RE.match(stripped):
            continue
        if index == 0 and not is_first_page and _PAGE_NUMBER_RE.match(stripped):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract cleaned, page-joined text from a ruling PDF.

    Args:
        pdf_path: Path to the source PDF file.

    Returns:
        The full ruling text with per-page header/footer boilerplate
        removed, pages joined with newlines in document order.
    """
    with pdfplumber.open(pdf_path) as pdf:
        pages = [
            _clean_page_text(page.extract_text() or "", is_first_page=(index == 0))
            for index, page in enumerate(pdf.pages)
        ]
    return "\n".join(pages)


def extract_ecli(pdf_path: Path) -> str | None:
    """Read the ruling's canonical ECLI citation out of its repeated footer.

    Opened independently from ``extract_pdf_text`` (a second, cheap pass
    over the same PDF) because the ECLI's only appearance in the document
    body is exactly the boilerplate footer line that ``extract_pdf_text``
    deliberately strips.

    Args:
        pdf_path: Path to the source PDF file.

    Returns:
        The ECLI string, e.g. ``"ECLI:BE:GHCC:2025:ARR.001"``, or ``None``
        if no page's raw text matched the expected pattern.
    """
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            match = ECLI_RE.search(page.extract_text() or "")
            if match:
                return match.group(0)
    return None


def _find_ruling_start(text: str) -> int | None:
    """Locate the start of the operative-ruling section, trying each marker.

    Args:
        text: The cleaned full ruling text.

    Returns:
        The character offset of the first matching marker, or ``None`` if
        none of ``_RULING_MARKERS`` were found.
    """
    for pattern in _RULING_MARKERS:
        match = pattern.search(text)
        if match:
            return match.start()
    return None


def split_into_sections(full_text: str) -> dict[str, str]:
    """Split cleaned ruling text into its four structural sections.

    Sections are located by their start markers and sliced from one
    marker's start to the next marker's start (or end of document). A
    marker that isn't found leaves the corresponding section as an empty
    string rather than raising, since a single missing marker shouldn't
    prevent the other, found sections from being returned.

    Args:
        full_text: The cleaned, page-joined ruling text.

    Returns:
        A mapping of section constant (see ``src.schemas``) to trimmed
        section text.
    """
    markers: list[tuple[str, int]] = []

    facts_match = _FACTS_MARKER_RE.search(full_text)
    if facts_match:
        markers.append((GHCC_SECTION_FACTS, facts_match.start()))

    arguments_match = _ARGUMENTS_MARKER_RE.search(full_text)
    if arguments_match:
        markers.append((GHCC_SECTION_ARGUMENTS, arguments_match.start()))

    reasoning_match = _REASONING_MARKER_RE.search(full_text)
    if reasoning_match:
        markers.append((GHCC_SECTION_REASONING, reasoning_match.start()))

    ruling_start = _find_ruling_start(full_text)
    if ruling_start is not None:
        markers.append((GHCC_SECTION_RULING, ruling_start))

    markers.sort(key=lambda marker: marker[1])

    sections: dict[str, str] = dict.fromkeys(
        (GHCC_SECTION_FACTS, GHCC_SECTION_ARGUMENTS, GHCC_SECTION_REASONING, GHCC_SECTION_RULING),
        "",
    )
    for position, (section, start) in enumerate(markers):
        end = (
            markers[position + 1][1] if position + 1 < len(markers) else len(full_text)
        )
        sections[section] = full_text[start:end].strip()
    return sections


def extract_case_sections(pdf_path: Path) -> dict[str, str]:
    """Extract and section-split the text of one ruling PDF.

    Args:
        pdf_path: Path to the source PDF file.

    Returns:
        A mapping of section constant (see ``src.schemas``) to extracted
        text, per ``split_into_sections``.
    """
    return split_into_sections(extract_pdf_text(pdf_path))
