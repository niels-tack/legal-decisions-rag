"""Extract structured sections from a Council of State (RVS) ruling PDF.

Uses PyMuPDF (``pymupdf``) for text extraction so we get font metadata
(size, weight) alongside the raw text. This lets us detect headings
reliably via two independent signals:

1. **Font signal**: a span whose font size exceeds the modal body-text size,
   or whose bold flag is set, is a candidate heading.
2. **Text signal**: ALL-CAPS lines and lines matching known RVS heading
   patterns are always treated as headings regardless of font metrics.

The combination is more robust than text-pattern matching alone because RVS
heading phrasing varies widely across cases, but the typographic conventions
(bold, slightly larger) are stable across the corpus.

Structure of an RVS ruling (from ``reference/sample_decisions/CoS_txt``):

    [preamble: Gezien / Gelet op / Gehoord blocks]
    OVERWEEGT WAT VOLGT :
    [section heading]
    [body text, possibly numbered paragraphs]
    ...
    OM DIE REDENEN
    BESLIST DE RAAD VAN STATE :
    Artikel 1.
    ...
    [signature block]

Everything before ``OVERWEEGT WAT VOLGT :`` is preamble and is discarded;
the signature block at the end is also excluded.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

# Running page-reference line printed in the header of every RVS page, e.g.
# "XII-5154-1/7". Stripped by coordinate-based header filtering rather than
# regex, but kept here as a backup pattern for any that slip through.
_PAGE_REF_RE = re.compile(r"^[A-Z]+-\d+-\d+/\d+\s*$")

# The "OVERWEEGT WAT VOLGT :" line marks the boundary between the procedural
# preamble and the substantive reasoning body. Everything before it is not
# indexed.
_BODY_START_RE = re.compile(r"OVERWEEGT\s+WAT\s+VOLGT\s*:", re.IGNORECASE)

# Closing signature patterns: once either appears, the ruling body is over.
_SIGNATURE_RE = re.compile(r"^De (?:griffier|voorzitter|wnd\. voorzitter)\b", re.IGNORECASE)

# Lines that are structurally ALL-CAPS headings regardless of font size.
# Matches lines composed entirely of uppercase letters, spaces, digits,
# colons, and dashes (covers "OM DIE REDENEN", "BESLIST DE RAAD VAN STATE :").
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9\s:,\-–]+$")

# Bold flag bit in PyMuPDF span flags field.
_BOLD_FLAG = 2**4


def _is_bold(flags: int) -> bool:
    """Return True if the PyMuPDF span bold flag is set."""
    return bool(flags & _BOLD_FLAG)


def _modal_font_size(doc: pymupdf.Document) -> float:
    """Return the most common font size across the document (= body text size).

    Args:
        doc: An open ``pymupdf.Document``.

    Returns:
        The modal font size, rounded to one decimal place. Falls back to
        ``10.0`` if no text spans are found.
    """
    sizes: list[float] = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        sizes.append(round(span["size"], 1))
    if not sizes:
        return 10.0
    return Counter(sizes).most_common(1)[0][0]


def _extract_lines(
    doc: pymupdf.Document, body_font_size: float
) -> list[tuple[str, bool]]:
    """Extract all post-header/footer lines with a per-line heading flag.

    Args:
        doc: An open ``pymupdf.Document``.
        body_font_size: The modal font size detected by ``_modal_font_size``.
            Lines with a larger size or bold weight are flagged as headings.

    Returns:
        A list of ``(line_text, is_heading)`` pairs in document order,
        with header/footer regions and empty lines already filtered out.
    """
    heading_size_threshold = body_font_size + 0.5
    lines: list[tuple[str, bool]] = []

    for page in doc:
        page_height = page.rect.height
        # Coordinates of the header and footer exclusion zones.
        header_bottom = page_height * 0.08
        footer_top = page_height * 0.92

        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            block_top = block["bbox"][1]
            block_bottom = block["bbox"][3]

            # Skip blocks that fall entirely within the header or footer zone.
            if block_bottom <= header_bottom or block_top >= footer_top:
                continue

            # A heading is only credible when it occupies its own block (i.e.
            # the block has a single line). Bold spans within a multi-line
            # block are inline emphasis, not section headings.
            is_single_line_block = len(block["lines"]) == 1

            for line in block["lines"]:
                line_text = " ".join(
                    span["text"] for span in line["spans"]
                ).strip()

                if not line_text or _PAGE_REF_RE.match(line_text):
                    continue

                # A line is a heading if:
                # (a) it is in ALL CAPS (structural markers like OM DIE REDENEN), or
                # (b) it is the sole line in its block AND any span is bold or larger.
                font_heading = is_single_line_block and any(
                    _is_bold(span["flags"])
                    or span["size"] >= heading_size_threshold
                    for span in line["spans"]
                    if span["text"].strip()
                )
                is_heading = bool(_ALL_CAPS_RE.match(line_text)) or font_heading
                lines.append((line_text, is_heading))

    return lines


def extract_sections(pdf_path: Path) -> dict[str, str]:
    """Extract the reasoning body of one RVS ruling as a heading-keyed dict.

    Discards the procedural preamble (everything before ``OVERWEEGT WAT
    VOLGT :``) and the closing signature block. The returned dict is in
    document order; keys are verbatim heading texts as they appear in the PDF.

    Args:
        pdf_path: Path to the RVS ruling PDF.

    Returns:
        ``{heading_text: body_text}`` mapping, ordered by document position.
        Sections with no body text (e.g. a heading immediately followed by
        another heading) are included with an empty string value.
    """
    doc = pymupdf.open(str(pdf_path))
    body_font_size = _modal_font_size(doc)
    all_lines = _extract_lines(doc, body_font_size)

    # Trim the preamble: find the OVERWEEGT WAT VOLGT line and start after it.
    body_start = 0
    for i, (text, _) in enumerate(all_lines):
        if _BODY_START_RE.search(text):
            body_start = i + 1
            break
    lines = all_lines[body_start:]

    # Trim the closing signature: stop at the first signature line.
    body_lines: list[tuple[str, bool]] = []
    for text, is_heading in lines:
        if _SIGNATURE_RE.match(text):
            break
        body_lines.append((text, is_heading))

    # Split into sections at heading boundaries.
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_body: list[str] = []

    for text, is_heading in body_lines:
        if is_heading:
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_body).strip()
            current_heading = text
            current_body = []
        else:
            if current_heading is not None:
                current_body.append(text)
            # Text before the first heading (rare) is silently discarded.

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_body).strip()

    return sections


def extract_ecli(pdf_path: Path) -> str | None:
    """Extract the ECLI citation from an RVS ruling PDF.

    RVS ECLIs follow the pattern ``ECLI:BE:RVS:<year>:A.<number>`` and
    typically appear in the document header or first page.

    Args:
        pdf_path: Path to the RVS ruling PDF.

    Returns:
        The ECLI string, or ``None`` if not found.
    """
    ecli_re = re.compile(r"ECLI:BE:(?:RVS|RVSE|RVSF):\d{4}:[A-Z]\.\d+")
    doc = pymupdf.open(str(pdf_path))
    for page in doc:
        text = page.get_text()
        match = ecli_re.search(text)
        if match:
            return match.group(0)
    return None
