"""Render one static, self-contained HTML page per ruling.

Reuses ``src.markdown_case`` for frontmatter/section parsing (the exact
same parsing ``src.indexing.build_index`` uses to build ``cases.db``) and
``src.indexing.build_index.split_into_paragraphs`` for the same
numbered-paragraph chunking, so every chunk a search result can point at
has a matching ``id`` anchor on its case page (``cases/<slug>.html#B.7.3``).

Pages carry the full ruling text and are pre-rendered at build time rather
than fetched from ``cases.db`` at runtime, per the technical requirements'
"no full text on the browser's query hot path" rule. They need no
JavaScript of their own - only the search page does.
"""

from __future__ import annotations

import argparse
import html
import logging
import re
from pathlib import Path

from src.indexing.build_index import split_into_paragraphs
from src.markdown_case import (
    SECTION_HEADERS,
    MalformedFrontmatterError,
    parse_case_file,
)
from src.schemas import CaseMetadata
from src.sources import SourceConfig, get_source

logger = logging.getLogger(__name__)

# Human-readable section titles, derived from the same headers
# src.markdown_case knows the Markdown assembler emits (stripping the "## ").
SECTION_DISPLAY_NAMES: dict[str, str] = {
    section: header.removeprefix("## ") for header, section in SECTION_HEADERS
}

# Splits a chunk's text into its own visual sub-paragraphs on blank lines,
# since a whole-section fallback chunk (no numbering) is often several
# prose paragraphs' worth of text collapsed into one chunk.
_BLANK_LINE_RE = re.compile(r"\n\s*\n")


def _render_chunk_body(text: str) -> str:
    """Render one chunk's text as one or more escaped HTML ``<p>`` blocks.

    Args:
        text: The chunk's plain text content.

    Returns:
        HTML markup: one ``<p>`` per blank-line-separated sub-paragraph.
    """
    paragraphs = [p.strip() for p in _BLANK_LINE_RE.split(text) if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)


def _render_section(section: str, section_text: str, source_config: SourceConfig) -> str:
    """Render one broad section (facts/arguments/reasoning/ruling) as HTML.

    Args:
        section: The section constant (see ``src.schemas``).
        section_text: That section's trimmed body text (may be empty).
        source_config: The issuing body's ``SourceConfig``, for
            ``split_into_paragraphs``.

    Returns:
        HTML markup for the section, or an empty string if the section had
        no text (e.g. a header the source ruling never emitted).
    """
    if not section_text:
        return ""

    chunk_html_blocks = []
    for paragraph_number, _parent_numbers, chunk_text in split_into_paragraphs(
        section_text, source_config
    ):
        body_html = _render_chunk_body(chunk_text)
        if paragraph_number:
            chunk_html_blocks.append(
                f'<div id="{html.escape(paragraph_number)}" class="paragraph">'
                f"{body_html}</div>"
            )
        else:
            chunk_html_blocks.append(body_html)

    return (
        f'<section id="section-{html.escape(section)}">\n'
        f"<h2>{html.escape(SECTION_DISPLAY_NAMES[section])}</h2>\n"
        + "\n".join(chunk_html_blocks)
        + "\n</section>"
    )


def _render_section_nav(sections: dict[str, str]) -> str:
    """Render a sticky navigator linking to each section actually present.

    A ruling can run to hundreds of thousands of words (see the functional
    requirements), so a way to jump straight to facts / arguments /
    reasoning / operative ruling - without endless scrolling - is real
    reading-usability, not decoration.

    Args:
        sections: Mapping of section constant to section body text.

    Returns:
        HTML markup for the nav, or an empty string if no section has text.
    """
    links = [
        f'<a href="#section-{html.escape(section)}">{html.escape(SECTION_DISPLAY_NAMES[section])}</a>'
        for section in SECTION_DISPLAY_NAMES
        if sections.get(section, "")
    ]
    if not links:
        return ""
    return '<nav class="section-nav">' + "".join(links) + "</nav>"


# Typography carries most of this page's design: comfortable measure (~70-80
# characters), generous line height, and a sticky section navigator so a
# 340,000-word ruling is still navigable - see context/Technical
# requirements.md and the UX assessment this reader page follows.
_STYLE = """
:root { color-scheme: light; }
body { font-family: "Segoe UI", system-ui, sans-serif; max-width: 42rem; margin: 0 auto; padding: 0 1rem 3rem; line-height: 1.6; color: #16181d; }
a.back { display: inline-block; margin: 1.25rem 0 0.5rem; color: #0b4a7a; text-decoration: none; }
a.back:hover { text-decoration: underline; }
h1 { font-size: 1.5rem; margin: 0.5rem 0; }
h2 { font-size: 1.2rem; margin-top: 2rem; }
dl.metadata { display: grid; grid-template-columns: max-content 1fr; gap: 0.3rem 1rem; margin: 1rem 0; font-size: 0.95rem; }
dl.metadata dt { font-weight: 600; color: #565d6b; }
.section-nav { position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #d8dce2; padding: 0.6rem 0; margin: 0 0 1rem; display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.9rem; }
.section-nav a { color: #0b4a7a; text-decoration: none; }
.section-nav a:hover { text-decoration: underline; }
.paragraph { scroll-margin-top: 3.5rem; }
.paragraph:target { background: #fff1a8; }
p { margin: 0 0 0.9rem; }
footer.reader-footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid #d8dce2; font-size: 0.85rem; color: #565d6b; }
a:focus-visible, button:focus-visible { outline: 3px solid #1a6ec7; outline-offset: 2px; }
"""


def render_case_page(metadata: CaseMetadata, sections: dict[str, str]) -> str:
    """Render one ruling's metadata and sections into a self-contained HTML page.

    Args:
        metadata: The ruling's validated frontmatter.
        sections: Mapping of section constant to section body text, per
            ``src.markdown_case.split_sections``.

    Returns:
        A full HTML document as a string.
    """
    source_config = get_source(metadata.source)
    keywords = ", ".join(metadata.keywords) if metadata.keywords else "–"

    metadata_rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
        for label, value in (
            ("Source", source_config.name),
            ("ECLI", metadata.ecli),
            ("Arrest number", metadata.arrest_number),
            ("Role number", metadata.role_number),
            ("Date", metadata.ruling_date.isoformat()),
            ("Language", metadata.language),
            ("Procedure type", metadata.procedure_type),
            ("Controlled norm", metadata.controlled_norm),
            ("Outcome", metadata.outcome),
            ("Keywords", keywords),
        )
    )

    sections_html = "\n".join(
        section_html
        for section in SECTION_DISPLAY_NAMES
        if (section_html := _render_section(section, sections.get(section, ""), source_config))
    )
    section_nav_html = _render_section_nav(sections)

    title = html.escape(metadata.title)
    ecli = html.escape(metadata.ecli)
    pdf_url = html.escape(metadata.source_pdf_url)

    return f"""<!doctype html>
<html lang="{html.escape(metadata.language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} – {ecli}</title>
<style>{_STYLE}</style>
</head>
<body>
<a class="back" href="../index.html">← Terug naar zoeken</a>
<header>
<h1>{title}</h1>
<dl class="metadata">{metadata_rows}</dl>
<p><a href="{pdf_url}">Origineel PDF bekijken</a></p>
</header>
{section_nav_html}
<main>
{sections_html}
</main>
<footer class="reader-footer">
<p>Dit is geen juridisch advies. Verifieer elke passage aan de hand van het originele PDF.</p>
</footer>
</body>
</html>
"""


def build_site(markdown_dir: Path, out_dir: Path) -> None:
    """Render one static HTML page per valid ruling into ``out_dir``.

    Args:
        markdown_dir: Directory containing one ``*.md`` file per ruling
            (same corpus ``src.indexing.build_index.build_index`` reads).
        out_dir: Destination directory for the rendered pages (created if
            missing). Each page is written to ``<out_dir>/<file_slug>.html``.

    Malformed frontmatter is logged and that file is skipped, matching
    ``build_index``'s behavior so both artifacts agree on which cases exist.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for md_file in sorted(markdown_dir.glob("*.md")):
        try:
            metadata, sections = parse_case_file(md_file)
        except MalformedFrontmatterError as exc:
            logger.warning("Skipping %s: %s", md_file, exc)
            continue
        page_html = render_case_page(metadata, sections)
        (out_dir / f"{metadata.file_slug}.html").write_text(page_html, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the ``python -m`` entrypoint.

    Returns:
        Parsed arguments with ``markdown_dir`` and ``out_dir`` as ``Path``.
    """
    parser = argparse.ArgumentParser(
        description="Render one static HTML page per ruling from Markdown case files."
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        required=True,
        help="Directory containing one *.md file per ruling.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Destination directory for rendered pages (created if missing).",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint: ``python -m src.site.build_site``."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = _parse_args()
    build_site(args.markdown_dir, args.out_dir)


if __name__ == "__main__":
    main()
