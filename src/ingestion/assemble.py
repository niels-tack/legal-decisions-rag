"""Render a ruling's metadata and section text into a Markdown case file.

Output format: a ``---``-delimited YAML frontmatter block matching
``CaseMetadata`` exactly, followed by ``##``-headed sections in document
order per the issuing body's ``SourceConfig``. The header strings are
load-bearing: ``src.markdown_case.split_sections`` splits on these exact
strings, so they must match verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from src.schemas import CaseMetadata
from src.sources import get_source


def render_markdown(metadata: CaseMetadata, sections: Mapping[str, str]) -> str:
    """Render one ruling's frontmatter and sections into a Markdown document.

    Args:
        metadata: The ruling's YAML frontmatter fields. The ``source`` field
            is used to look up the issuing body's section structure from
            ``src.sources.SOURCES``.
        sections: A mapping of section label to section body text. Missing
            sections render as an empty body under their header rather than
            omitting the header, so the document's structure stays
            predictable for downstream parsing.

    Returns:
        The full Markdown document text, ready to write to disk.
    """
    source_config = get_source(metadata.source)

    # mode="python" keeps ruling_date as a datetime.date object rather than
    # a pre-serialized string, so yaml.safe_dump emits it as an unquoted
    # ISO date scalar that yaml.safe_load round-trips back into a date.
    frontmatter_data = metadata.model_dump(mode="python")
    frontmatter_yaml = yaml.safe_dump(
        frontmatter_data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    body_blocks = [
        f"{markdown_header}\n\n{sections.get(section_label, '').strip()}\n"
        for markdown_header, section_label in source_config.section_headers
    ]

    return f"---\n{frontmatter_yaml}---\n\n" + "\n".join(body_blocks)


def write_case_file(
    output_dir: Path, metadata: CaseMetadata, sections: Mapping[str, str]
) -> Path:
    """Render and write one ruling's Markdown file.

    Args:
        output_dir: Directory the file is written into (created if it
            doesn't exist yet).
        metadata: The ruling's YAML frontmatter fields.
        sections: A mapping of section constant to section body text.

    Returns:
        The path of the written file, ``<output_dir>/<file_slug>.md``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{metadata.file_slug}.md"
    output_path.write_text(render_markdown(metadata, sections), encoding="utf-8")
    return output_path
