"""Weekly ingestion pipeline CLI: discover, download, extract, assemble, publish.

Wires ``src.ingestion.discover``, ``extract``, and ``assemble`` into the
offline weekly job described in the project's functional requirements:
check the Court's listing for rulings not yet present as a Markdown file,
download and process each one, and - only when explicitly requested via
``--push`` - commit and push the results to the public GitHub repository
from the maintainer's own machine.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import time
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.ingestion import assemble, discover, extract
from src.schemas import CaseMetadata
from src.sources import SOURCE_CONSTITUTIONAL_COURT

logger = logging.getLogger(__name__)

DATA_SUBPATH = Path("Constitutional_Court_Belgium") / "NL"
DEFAULT_DELAY_SECONDS = 2.0
MAX_TITLE_LENGTH = 200
LOG_DIR = Path("logs")


def _configure_logging(log_dir: Path = LOG_DIR) -> None:
    """Set up console and dated file handlers on the root logger.

    Replaces ``logging.basicConfig`` in ``main()`` so that every INFO-level
    message is both printed to the terminal and appended to a dated log file
    under ``log_dir``. Safe to call multiple times: a second call appends a
    new ``FileHandler`` (dated log rolls over each day) but never duplicates
    the ``StreamHandler``.

    Args:
        log_dir: Directory to write ``ingestion-YYYY-MM-DD.log`` into.
            Created automatically if it does not exist.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"ingestion-{date.today().isoformat()}.log"
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Add a StreamHandler only if none exists yet (avoids duplicates in tests
    # that call main() more than once without resetting the root logger).
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    ):
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def build_session(
    total_retries: int = 3, backoff_factor: float = 1.0
) -> requests.Session:
    """Build a polite ``requests.Session`` with retry/backoff for unattended use.

    Replaces the prototype pipeline's bare ``wget.download()`` call, which
    has no retry or rate-limiting behavior and isn't acceptable for an
    unattended weekly job hitting a third party's server.

    Args:
        total_retries: Maximum number of retries per request for the
            configured status codes.
        backoff_factor: Multiplier for the exponential backoff between
            retries.

    Returns:
        A configured ``requests.Session``.
    """
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "legal-decisions-rag-ingestion/1.0 (+https://github.com/)"}
    )
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def download_pdf(
    url: str, dest_path: Path, session: requests.Session, timeout: float = 60.0
) -> None:
    """Download one ruling PDF to disk.

    Args:
        url: The source PDF URL.
        dest_path: Local file path to write the PDF bytes to.
        session: A session (ideally from ``build_session``) handling
            retry/backoff.
        timeout: Per-request timeout in seconds.

    Raises:
        requests.HTTPError: If the server returns a non-2xx status code
            after retries are exhausted.
    """
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(response.content)


def _build_title(procedure_type: str, controlled_norm: str) -> str:
    """Synthesize a short human-readable title from discovered metadata.

    The case overview listing carries no dedicated title field, so this
    combines the two fields that most concisely describe what the ruling is
    about, truncating if the combined text runs long.

    Args:
        procedure_type: e.g. ``"Prejudiciële vraag"``.
        controlled_norm: The law/article under constitutional review.

    Returns:
        A title string bounded to ``MAX_TITLE_LENGTH`` characters.
    """
    title = f"{procedure_type} - {controlled_norm}".strip(" -")
    if len(title) > MAX_TITLE_LENGTH:
        title = title[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return title


def build_case_metadata(
    discovered: discover.DiscoveredRuling, file_slug: str, ecli: str
) -> CaseMetadata:
    """Combine a discovered listing record and PDF-derived ECLI into full metadata.

    Args:
        discovered: One record from ``discover.parse_listing_html``.
        file_slug: The file/URL slug derived from the PDF URL.
        ecli: The canonical ECLI citation read from the PDF's footer.

    Returns:
        A validated ``CaseMetadata`` instance ready for
        ``assemble.write_case_file``.
    """
    return CaseMetadata(
        source=SOURCE_CONSTITUTIONAL_COURT,
        ecli=ecli,
        arrest_number=discovered["arrest_number"],
        role_number=discovered["role_number"],
        file_slug=file_slug,
        ruling_date=discovered["ruling_date"],
        language="nl",
        procedure_type=discovered["procedure_type"],
        controlled_norm=discovered["controlled_norm"],
        outcome=discovered["outcome"],
        keywords=discovered["keywords"],
        source_pdf_url=discover.ghcc_permalink_pdf(
            discovered["arrest_number"], language="nl"
        ),
        title=_build_title(discovered["procedure_type"], discovered["controlled_norm"]),
    )


def existing_file_slugs(output_dir: Path) -> set[str]:
    """List file slugs already published as Markdown in ``output_dir``.

    Args:
        output_dir: The directory rulings are written to.

    Returns:
        The set of ``.md`` filenames' stems, or an empty set if the
        directory doesn't exist yet (first-ever run).
    """
    if not output_dir.exists():
        return set()
    return {path.stem for path in output_dir.glob("*.md")}


def process_ruling(
    discovered: discover.DiscoveredRuling,
    output_dir: Path,
    pdf_cache_dir: Path,
    session: requests.Session,
    label: str = "",
) -> Path:
    """Download, extract, and assemble the Markdown file for one new ruling.

    Args:
        discovered: One record from ``discover.parse_listing_html``.
        output_dir: Directory the finished Markdown file is written into.
        pdf_cache_dir: Directory the downloaded PDF is kept in.
        session: A polite requests session for the PDF download.
        label: Optional progress prefix (e.g. ``"[2/5]"``) shown in log lines.

    Returns:
        The path of the written Markdown file.

    Raises:
        ValueError: If no ECLI could be found in the downloaded PDF.
    """
    file_slug = discover.file_slug_from_pdf_url(discovered["pdf_url"])
    tag = f"{label} {file_slug}" if label else file_slug

    logger.info("%s - downloading PDF...", tag)
    pdf_path = pdf_cache_dir / f"{file_slug}.pdf"
    download_pdf(
        discover.ghcc_pdf_download_url(file_slug, language="nl"), pdf_path, session
    )

    logger.info("%s - extracting ECLI...", tag)
    ecli = extract.extract_ecli(pdf_path)
    if ecli is None:
        raise ValueError(f"Could not find an ECLI in downloaded PDF: {pdf_path}")

    logger.info("%s - extracting sections...", tag)
    sections = extract.extract_case_sections(pdf_path)

    logger.info("%s - assembling Markdown...", tag)
    metadata = build_case_metadata(discovered, file_slug, ecli)
    output_path = assemble.write_case_file(output_dir, metadata, sections)

    logger.info("%s - done -> %s", tag, output_path.name)
    return output_path


def push_to_remote(data_repo_path: Path, new_file_count: int) -> None:
    """Commit and push newly written case files from the data repo.

    Only ever invoked when the caller explicitly passes ``--push``; this
    function itself performs no such check and must not be wired up to run
    on its own. Kept as a thin, mockable wrapper around ``git`` calls so
    tests can verify the capability exists without ever shelling out for
    real.

    Args:
        data_repo_path: Root of the public data repository's local clone.
        new_file_count: Number of new files added, used in the commit message.

    Raises:
        subprocess.CalledProcessError: If any git command exits non-zero.
    """
    subprocess.run(["git", "add", "."], cwd=data_repo_path, check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            f"Add {new_file_count} new ruling(s) from weekly ingestion run",
        ],
        cwd=data_repo_path,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=data_repo_path, check=True)


def run_pipeline(
    data_repo_path: Path,
    year: int | None = None,
    push: bool = False,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    session: requests.Session | None = None,
) -> list[Path]:
    """Run one full weekly ingestion pass for a given year.

    Discovery uses the Court's public document server
    (``https://nl.const-court.be/public/n/{year}/``), a plain Apache directory
    listing that is accessible without TLS fingerprinting or JavaScript
    rendering. Per-ruling metadata is then fetched from each ruling's info card
    page (``https://nl.const-court.be/ARR/{number}/{year}``).

    Args:
        data_repo_path: Root of the public data repository's local clone.
        year: Calendar year to discover rulings for. Defaults to the
            current year, since the weekly job's purpose is to catch newly
            published rulings.
        push: If True, commit and push new files to the data repo's remote
            after processing. Defaults to False; this must be requested
            explicitly, never inferred.
        delay_seconds: Politeness delay observed between successive PDF
            downloads.
        session: An existing session to reuse; a fresh polite session (see
            ``build_session``) is created if omitted.

    Returns:
        Paths of newly written Markdown files (empty if nothing was new).
    """
    target_year = year if year is not None else date.today().year
    output_dir = data_repo_path / DATA_SUBPATH
    pdf_cache_dir = data_repo_path / ".pdf_cache"
    http_session = session or build_session()

    # ------------------------------------------------------------------
    # Phase 1: document server discovery
    # ------------------------------------------------------------------
    logger.info("=== Phase 1/3: Document server discovery (year=%d) ===", target_year)
    known_slugs = existing_file_slugs(output_dir)
    server_html = discover.fetch_document_server_listing(
        target_year, session=http_session
    )
    all_slugs = discover.parse_document_server_listing(server_html, target_year)
    new_slugs = [s for s in all_slugs if s not in known_slugs]
    logger.info(
        "Phase 1/3: %d ruling(s) on document server, %d new (already known: %d).",
        len(all_slugs),
        len(new_slugs),
        len(known_slugs),
    )

    if not new_slugs:
        logger.info("Nothing to do.")
        return []

    # ------------------------------------------------------------------
    # Phase 2: fetch info cards for each new slug
    # ------------------------------------------------------------------
    total_new = len(new_slugs)
    logger.info(
        "=== Phase 2/3: Fetching info cards for %d new ruling(s) ===", total_new
    )
    discovered_rulings: list[discover.DiscoveredRuling] = []
    for idx, slug in enumerate(new_slugs, start=1):
        arrest_number = discover.arrest_number_from_slug(slug)
        logger.info(
            "[%d/%d] %s - fetching info card (arrest %s)...",
            idx,
            total_new,
            slug,
            arrest_number,
        )
        try:
            card_html = discover.fetch_info_card_html(
                arrest_number, session=http_session
            )
            ruling = discover.parse_info_card(card_html, slug)
        except Exception as exc:
            logger.warning(
                "[%d/%d] %s - info card failed (%s): %s - skipping.",
                idx,
                total_new,
                slug,
                arrest_number,
                exc,
            )
            continue
        discovered_rulings.append(ruling)
    logger.info(
        "Phase 2/3: %d/%d ruling(s) ready for processing.",
        len(discovered_rulings),
        total_new,
    )

    # ------------------------------------------------------------------
    # Phase 3: download, extract, and assemble each ruling
    # ------------------------------------------------------------------
    total_process = len(discovered_rulings)
    logger.info("=== Phase 3/3: Processing %d ruling(s) ===", total_process)
    written_paths: list[Path] = []
    for idx, ruling in enumerate(discovered_rulings, start=1):
        if written_paths:
            time.sleep(delay_seconds)
        label = f"[{idx}/{total_process}]"
        written_paths.append(
            process_ruling(ruling, output_dir, pdf_cache_dir, http_session, label=label)
        )

    logger.info("=== Done: wrote %d new case file(s) ===", len(written_paths))

    if push and written_paths:
        logger.info("Pushing %d new file(s) to remote...", len(written_paths))
        push_to_remote(data_repo_path, len(written_paths))

    return written_paths


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the weekly ingestion CLI.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Weekly ingestion run: discover new Constitutional Court rulings, "
            "download, extract, and assemble them into Markdown case files."
        )
    )
    parser.add_argument(
        "--data-repo-path",
        type=Path,
        required=True,
        help="Root of the local clone of the public data repository.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Calendar year to discover rulings for (defaults to the current year).",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        default=False,
        help=(
            "Commit and push new Markdown files to the data repo's remote. "
            "Off by default; must be requested explicitly."
        ),
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Politeness delay between successive PDF downloads.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for the weekly ingestion run.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.
    """
    _configure_logging()
    args = _parse_args(argv)
    run_pipeline(
        data_repo_path=args.data_repo_path,
        year=args.year,
        push=args.push,
        delay_seconds=args.delay_seconds,
    )


if __name__ == "__main__":
    main()
