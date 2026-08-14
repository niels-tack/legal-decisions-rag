"""Tests for src.markdown_case's frontmatter/section parsing.

Exercises the parsing functions shared by src.indexing.build_index and
src.site.build_site directly, against both small synthetic strings (for
edge cases) and the real fixture files under tests/indexing/fixtures (for
an end-to-end parse_case_file check).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.markdown_case import (
    MalformedFrontmatterError,
    parse_case_file,
    parse_metadata,
    split_frontmatter,
    split_sections,
)
from src.schemas import (
    SECTION_ARGUMENTS,
    SECTION_FACTS,
    SECTION_REASONING,
    SECTION_RULING,
)

FIXTURES_DIR = Path(__file__).parent / "indexing" / "fixtures"


def test_split_frontmatter_separates_yaml_from_body() -> None:
    """The YAML block and body are split at the closing '---' delimiter."""
    frontmatter_yaml, body = split_frontmatter("---\nfoo: bar\n---\n\nBody text.")

    assert frontmatter_yaml == "foo: bar"
    assert body == "Body text."


def test_split_frontmatter_raises_without_delimited_block() -> None:
    """A file with no leading '---' block is rejected, not silently parsed."""
    with pytest.raises(MalformedFrontmatterError):
        split_frontmatter("No frontmatter here at all.")


def test_parse_metadata_rejects_unparsable_yaml() -> None:
    """Invalid YAML syntax raises rather than propagating a raw YAMLError."""
    with pytest.raises(MalformedFrontmatterError):
        parse_metadata("source: [unterminated")


def test_parse_metadata_rejects_non_mapping_yaml() -> None:
    """YAML that parses to something other than a mapping (e.g. a list) is rejected."""
    with pytest.raises(MalformedFrontmatterError):
        parse_metadata("- just\n- a\n- list\n")


def test_parse_metadata_rejects_missing_required_field() -> None:
    """A CaseMetadata validation failure (missing required field) is rejected."""
    with pytest.raises(MalformedFrontmatterError):
        parse_metadata("source: GHCC\necli: ECLI:BE:GHCC:2025:ARR.001\n")


def test_split_sections_orders_by_position_not_declaration_order() -> None:
    """Sections are sliced in the order their headers actually appear."""
    body = (
        "## Beschikking\n\nRuling text.\n\n"
        "## Feiten en rechtspleging\n\nFacts text."
    )

    sections = split_sections(body)

    assert sections[SECTION_RULING] == "Ruling text."
    assert sections[SECTION_FACTS] == "Facts text."
    assert SECTION_ARGUMENTS not in sections
    assert SECTION_REASONING not in sections


def test_parse_case_file_reads_real_fixture() -> None:
    """parse_case_file combines metadata + sections for a real fixture file."""
    metadata, sections = parse_case_file(FIXTURES_DIR / "case_001.md")

    assert metadata.ecli == "ECLI:BE:GHCC:2025:ARR.001"
    assert metadata.source == "GHCC"
    assert "discriminatie" in sections[SECTION_FACTS].lower()


def test_parse_case_file_raises_on_broken_fixture() -> None:
    """The fixture with missing required frontmatter fields raises, not silently skips."""
    with pytest.raises(MalformedFrontmatterError):
        parse_case_file(FIXTURES_DIR / "case_broken_frontmatter.md")
