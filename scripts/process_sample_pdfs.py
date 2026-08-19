"""Process the checked-in sample PDFs into Markdown, without any network access.

Runs the real extraction logic (``src.ingestion.extract``, backed by
``pdfplumber``) against ``reference/sample_decisions/CoC_pdf/*.pdf`` - the
part of the ingestion pipeline with genuine parsing risk (PDF layout
quirks, section-marker regexes) - so ``ecli`` and every section's text
below are real, extracted text.

The listing-page fields (case number, docket number, procedure type,
controlled norm, outcome, keywords, ruling date) normally come from
``src.ingestion.discover``'s live scrape of the Court's case overview page,
which this script deliberately never calls (no outbound network access).
Those fields are filled with clearly-labeled placeholders here instead -
this script is a local processing smoke test/demo data generator, not a
substitute for a real ingestion run.

Usage::

    uv run python scripts/process_sample_pdfs.py \\
        --pdf-dir reference/sample_decisions/CoC_pdf \\
        --out-dir sample-data/markdown
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date
from pathlib import Path

# Standalone script outside the src package - add the repo root to sys.path
# so `from src...` resolves regardless of the caller's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion import assemble, extract  # noqa: E402
from src.schemas import CaseMetadata  # noqa: E402
from src.sources import SOURCE_CONSTITUTIONAL_COURT  # noqa: E402

logger = logging.getLogger(__name__)

PLACEHOLDER_NOTE = "Placeholder (no live scrape - see scripts/process_sample_pdfs.py)"

# Matches the arrest-number sequence in a file slug, e.g. "2025-001n" -> ("2025", "001").
_SLUG_RE = re.compile(r"^(\d{4})-(\d+)[a-z]?$")


def _derive_case_number(file_slug: str) -> str:
    """Derive a plausible case number from the file slug's year/sequence.

    Args:
        file_slug: The PDF filename without extension, e.g. ``"2025-001n"``.

    Returns:
        E.g. ``"1/2025"`` - the real convention observed across the sample
        corpus - or the raw slug if it doesn't match that pattern.
    """
    match = _SLUG_RE.match(file_slug)
    if not match:
        return file_slug
    year, sequence = match.groups()
    return f"{int(sequence)}/{year}"


def process_sample_pdfs(pdf_dir: Path, out_dir: Path) -> list[Path]:
    """Extract + assemble Markdown for every sample PDF, skipping unreadable ones.

    Args:
        pdf_dir: Directory of source PDFs (e.g.
            ``reference/sample_decisions/CoC_pdf``).
        out_dir: Destination directory for the rendered Markdown files.

    Returns:
        Paths of the written Markdown files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        file_slug = pdf_path.stem
        ecli = extract.extract_ecli(pdf_path)
        if ecli is None:
            logger.warning("Skipping %s: no ECLI found in PDF", pdf_path)
            continue

        sections = extract.extract_case_sections(pdf_path)
        metadata = CaseMetadata(
            source=SOURCE_CONSTITUTIONAL_COURT,
            ecli=ecli,
            case_number=_derive_case_number(file_slug),
            docket_number=PLACEHOLDER_NOTE,
            file_slug=file_slug,
            ruling_date=date(2025, 1, 1),
            language="nl",
            procedure_type=PLACEHOLDER_NOTE,
            controlled_norm=PLACEHOLDER_NOTE,
            outcome=PLACEHOLDER_NOTE,
            keywords=[],
            source_pdf_url=f"https://nl.const-court.be/public/n/{file_slug}.pdf",
            title=f"Sample ruling {file_slug} (real extracted text, placeholder metadata)",
        )
        written.append(assemble.write_case_file(out_dir, metadata, sections))

    return written


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the CLI entrypoint.

    Returns:
        Parsed arguments with ``pdf_dir`` and ``out_dir`` as ``Path``.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Process the checked-in sample PDFs into Markdown, using real "
            "PDF extraction but no network access (placeholder listing metadata)."
        )
    )
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint: ``python scripts/process_sample_pdfs.py``."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = _parse_args()
    written = process_sample_pdfs(args.pdf_dir, args.out_dir)
    logger.info("Wrote %d Markdown file(s) to %s", len(written), args.out_dir)


if __name__ == "__main__":
    main()
