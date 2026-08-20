"""Tests for src.ingestion.pipeline. No live network access anywhere here.

PDF downloads are exercised against a small fake session object rather than
a real ``requests.Session``; the discovery and extraction steps are
monkeypatched so the pipeline's orchestration logic (skip-known-slugs,
politeness delay, the --push gate) can be verified without a live site or a
real PDF.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
import requests
from requests.adapters import HTTPAdapter
from src.ingestion import discover, extract, pipeline
from src.sources import (
    GHCC_SECTION_ARGUMENTS,
    GHCC_SECTION_FACTS,
    GHCC_SECTION_REASONING,
    GHCC_SECTION_RULING,
)


def _make_discovered(
    pdf_url: str, case_number: str = "1/2025"
) -> discover.DiscoveredRuling:
    """Build a minimal DiscoveredRuling record for pipeline tests."""
    return discover.DiscoveredRuling(
        case_number=case_number,
        docket_number="8115",
        ruling_date=date(2025, 1, 9),
        procedure_type="Prejudiciële vraag",
        challenged_norm="Artikel 1 van de wet van 19 juli 1991",
        applied_norm="",
        controlled_norm="Artikel 1 van de wet van 19 juli 1991",
        outcome="Geen antwoord vereist",
        keywords=["Bevolkingsregister"],
        pdf_url=pdf_url,
    )


class _FakeResponse:
    """Minimal stand-in for requests.Response used by download_pdf tests."""

    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession:
    """Minimal stand-in for requests.Session used by download_pdf tests."""

    def __init__(self, content: bytes = b"%PDF-1.4 fake content") -> None:
        self._content = content
        self.requested_urls: list[str] = []

    def get(self, url: str, timeout: float = 60.0) -> _FakeResponse:
        self.requested_urls.append(url)
        return _FakeResponse(self._content)


def _unused_session() -> requests.Session:
    """A typed placeholder for a session argument that is never actually used.

    Several tests below monkeypatch out the only function that would touch
    the session (``download_pdf`` or ``discover.fetch_listing_html``), so the
    real value passed through doesn't matter - only its static type does.
    """
    return cast(requests.Session, object())


def test_build_session_sets_user_agent_and_mounts_retry_adapter() -> None:
    """build_session should return a session with a UA and retrying adapters."""
    session = pipeline.build_session()

    assert "legal-decisions-rag-ingestion" in session.headers["User-Agent"]
    https_adapter = session.get_adapter("https://example.org")
    assert isinstance(https_adapter, HTTPAdapter)
    assert https_adapter.max_retries.total == 3


def test_download_pdf_writes_response_bytes_to_dest_path(tmp_path: Path) -> None:
    """download_pdf should write the response body verbatim to dest_path."""
    session = _FakeSession(content=b"%PDF-1.4 hello world")
    dest_path = tmp_path / "nested" / "2025-001n.pdf"

    pipeline.download_pdf(
        "https://example.org/2025-001n.pdf", dest_path, cast(requests.Session, session)
    )

    assert dest_path.read_bytes() == b"%PDF-1.4 hello world"
    assert session.requested_urls == ["https://example.org/2025-001n.pdf"]


def test_download_pdf_raises_on_http_error(tmp_path: Path) -> None:
    """A non-2xx response should raise rather than silently writing an empty/error file."""
    session = _FakeSession()
    session.get = lambda url, timeout=60.0: _FakeResponse(b"", status_code=404)  # type: ignore[method-assign]

    with pytest.raises(requests.HTTPError):
        pipeline.download_pdf(
            "https://example.org/missing.pdf",
            tmp_path / "x.pdf",
            cast(requests.Session, session),
        )


def test_build_case_metadata_combines_discovered_and_ecli() -> None:
    """build_case_metadata should merge listing fields with the PDF-derived ECLI."""
    discovered = _make_discovered(
        "https://www.const-court.be/public/n/2025/2025-001n.pdf"
    )

    metadata = pipeline.build_case_metadata(
        discovered, file_slug="2025-001n", ecli="ECLI:BE:GHCC:2025:ARR.001"
    )

    assert metadata.source == "GHCC"
    assert metadata.ecli == "ECLI:BE:GHCC:2025:ARR.001"
    assert metadata.file_slug == "2025-001n"
    assert metadata.case_number == "1/2025"
    assert metadata.source_pdf_url == discover.ghcc_permalink_pdf(
        discovered["case_number"], language="nl"
    )
    assert metadata.source_pdf_url == "https://nl.const-court.be/1/2025.pdf"
    assert metadata.title == "Artikel 1 van de wet van 19 juli 1991"


def test_build_title_omits_procedure_when_norm_is_available() -> None:
    """Titles should avoid repeating procedure metadata already shown separately."""
    title = pipeline._build_title(
        "Beroepen tot vernietiging",
        "Decreet van de Franse Gemeenschap van 6 april 1998",
    )

    assert title == "Decreet van de Franse Gemeenschap van 6 april 1998"


def test_build_title_falls_back_to_procedure_without_norm() -> None:
    """A procedure remains useful as a title when no norm was discovered."""
    assert pipeline._build_title("Prejudiciële vraag", None) == "Prejudiciële vraag"


@pytest.mark.parametrize(
    ("ecli", "file_slug", "case_number", "should_warn"),
    [
        ("ECLI:BE:GHCC:2025:ARR.001", "2025-001n", "1/2025", False),
        ("ECLI:BE:GHCC:2025:ARR.100", "2026-090n", "90/2026", True),
    ],
)
def test_warn_on_ecli_identity_mismatch(
    ecli: str,
    file_slug: str,
    case_number: str,
    should_warn: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Matching and delayed-publication ECLIs are handled deterministically."""
    pipeline._warn_on_ecli_identity_mismatch(ecli, file_slug, case_number, "test")

    assert ("identity mismatch" in caplog.text) is should_warn


def test_build_title_truncates_long_combined_text() -> None:
    """A very long controlled norm should be truncated rather than left unbounded."""
    title = pipeline._build_title("Prejudiciële vraag", "x" * 500)

    assert len(title) <= pipeline.MAX_TITLE_LENGTH
    assert title.endswith("…")


def test_existing_file_slugs_reads_md_stems(tmp_path: Path) -> None:
    """existing_file_slugs should return the .md filename stems already on disk."""
    (tmp_path / "2025-001n.md").write_text("dummy", encoding="utf-8")
    (tmp_path / "2025-002n.md").write_text("dummy", encoding="utf-8")
    (tmp_path / "not-a-case.txt").write_text("dummy", encoding="utf-8")

    assert pipeline.existing_file_slugs(tmp_path) == {"2025-001n", "2025-002n"}


def test_existing_file_slugs_returns_empty_set_for_missing_directory(
    tmp_path: Path,
) -> None:
    """A never-yet-created output directory should report no known slugs."""
    assert pipeline.existing_file_slugs(tmp_path / "does-not-exist") == set()


def _fake_download_pdf(
    url: str, dest_path: Path, session: object, timeout: float = 60.0
) -> None:
    """Stand-in for download_pdf that writes a placeholder file without any network access."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(b"fake-pdf")


def test_process_ruling_writes_markdown_with_merged_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """process_ruling should download, extract, and assemble one ruling end to end."""
    discovered = _make_discovered(
        "https://www.const-court.be/public/n/2025/2025-001n.pdf"
    )
    output_dir = tmp_path / "out"
    pdf_cache_dir = tmp_path / "pdfs"

    monkeypatch.setattr(pipeline, "download_pdf", _fake_download_pdf)
    monkeypatch.setattr(
        extract, "extract_ecli", lambda pdf_path: "ECLI:BE:GHCC:2025:ARR.001"
    )
    monkeypatch.setattr(
        extract,
        "extract_case_sections",
        lambda pdf_path: {
            GHCC_SECTION_FACTS: "I. Facts",
            GHCC_SECTION_ARGUMENTS: "- A - Arguments",
            GHCC_SECTION_REASONING: "- B - Reasoning",
            GHCC_SECTION_RULING: "Om die redenen, Ruling",
        },
    )

    output_path = pipeline.process_ruling(
        discovered,
        output_dir,
        pdf_cache_dir,
        session=_unused_session(),
    )

    assert output_path == output_dir / "2025-001n.md"
    content = output_path.read_text(encoding="utf-8")
    assert "ecli: ECLI:BE:GHCC:2025:ARR.001" in content
    assert "## Feiten en rechtspleging" in content
    assert (pdf_cache_dir / "2025-001n.pdf").read_bytes() == b"fake-pdf"


def test_process_ruling_writes_missing_ecli_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF with no discoverable ECLI should still produce a marked case file."""
    discovered = _make_discovered(
        "https://www.const-court.be/public/n/2025/2025-001n.pdf"
    )

    monkeypatch.setattr(pipeline, "download_pdf", _fake_download_pdf)
    monkeypatch.setattr(extract, "extract_ecli", lambda pdf_path: None)
    monkeypatch.setattr(
        extract,
        "extract_case_sections",
        lambda pdf_path: {
            GHCC_SECTION_FACTS: "I. Facts",
            GHCC_SECTION_ARGUMENTS: "- A - Arguments",
            GHCC_SECTION_REASONING: "- B - Reasoning",
            GHCC_SECTION_RULING: "Om die redenen, Ruling",
        },
    )

    output_path = pipeline.process_ruling(
        discovered,
        tmp_path / "out",
        tmp_path / "pdfs",
        session=_unused_session(),
    )

    assert output_path.exists()
    assert "ecli: null" in output_path.read_text(encoding="utf-8")


def _fake_discovery(monkeypatch: pytest.MonkeyPatch, slugs: list[str]) -> None:
    """Patch discovery calls to return ``slugs`` without any network access."""
    monkeypatch.setattr(
        discover,
        "fetch_document_server_listing",
        lambda year, session=None, language="nl": "<html></html>",
    )
    monkeypatch.setattr(
        discover,
        "parse_document_server_listing",
        lambda html, year, language="nl": slugs,
    )
    monkeypatch.setattr(
        discover,
        "fetch_listing_html",
        lambda year, language="nl", session=None, timeout=30.0: "<html></html>",
    )
    monkeypatch.setattr(
        discover,
        "parse_listing_html",
        lambda html, language="nl": [
            _make_discovered(
                discover.ghcc_pdf_download_url(slug),
                case_number=discover.case_number_from_slug(slug),
            )
            for slug in slugs
        ],
    )


def test_run_pipeline_skips_rulings_already_present_as_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ruling whose .md file already exists should not be re-downloaded."""
    data_repo_path = tmp_path
    output_dir = data_repo_path / pipeline.DATA_SUBPATH
    output_dir.mkdir(parents=True)
    (output_dir / "2025-001n.md").write_text("already here", encoding="utf-8")

    _fake_discovery(monkeypatch, ["2025-001n", "2025-002n"])
    processed: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "process_ruling",
        lambda ruling, out_dir, cache_dir, session, **kwargs: (
            processed.append(ruling["case_number"]) or out_dir / "dummy.md"
        ),
    )
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    written = pipeline.run_pipeline(
        data_repo_path, year=2025, session=_unused_session()
    )

    assert processed == ["2/2025"]
    assert len(written) == 1


def test_run_pipeline_does_not_push_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """push_to_remote must never run unless --push (push=True) was explicitly set."""
    _fake_discovery(monkeypatch, ["2025-001n"])
    monkeypatch.setattr(
        pipeline,
        "process_ruling",
        lambda ruling, out_dir, cache_dir, session, **kwargs: out_dir / "x.md",
    )
    push_calls: list[Any] = []
    monkeypatch.setattr(
        pipeline, "push_to_remote", lambda repo_path, count: push_calls.append(count)
    )

    pipeline.run_pipeline(tmp_path, year=2025, push=False, session=_unused_session())

    assert push_calls == []


def test_run_pipeline_pushes_only_when_explicitly_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With push=True and at least one new file, push_to_remote should run exactly once."""
    _fake_discovery(monkeypatch, ["2025-001n"])
    monkeypatch.setattr(
        pipeline,
        "process_ruling",
        lambda ruling, out_dir, cache_dir, session, **kwargs: out_dir / "x.md",
    )
    push_calls: list[int] = []
    monkeypatch.setattr(
        pipeline, "push_to_remote", lambda repo_path, count: push_calls.append(count)
    )

    pipeline.run_pipeline(tmp_path, year=2025, push=True, session=_unused_session())

    assert push_calls == [1]


def test_push_to_remote_never_shells_out_for_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """push_to_remote's git calls must be mockable so a test never triggers a real push."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path, check: bool) -> None:
        calls.append(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    pipeline.push_to_remote(tmp_path, new_file_count=2)

    assert calls == [
        ["git", "add", "."],
        ["git", "commit", "-m", "Add 2 new ruling(s) from weekly ingestion run"],
        ["git", "push"],
    ]


def test_parse_args_defaults_push_to_false() -> None:
    """--push should default to False so publishing is always an explicit opt-in."""
    args = pipeline._parse_args(["--data-repo-path", "/tmp/data"])

    assert args.push is False
    assert args.year is None
    assert args.delay_seconds == pipeline.DEFAULT_DELAY_SECONDS


def test_parse_args_accepts_push_flag() -> None:
    """Passing --push should set push to True."""
    args = pipeline._parse_args(
        ["--data-repo-path", "/tmp/data", "--push", "--year", "2024"]
    )

    assert args.push is True
    assert args.year == 2024


def test_main_wires_parsed_args_into_run_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() should forward parsed CLI arguments into run_pipeline unchanged."""
    captured: dict[str, Any] = {}

    def fake_run_pipeline(
        data_repo_path: Path,
        year: int | None = None,
        push: bool = False,
        delay_seconds: float = pipeline.DEFAULT_DELAY_SECONDS,
        session: object | None = None,
        force: bool = False,
        use_pdf_cache: bool = True,
    ) -> list[Path]:
        captured.update(
            data_repo_path=data_repo_path,
            year=year,
            push=push,
            delay_seconds=delay_seconds,
            force=force,
            use_pdf_cache=use_pdf_cache,
        )
        return []

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)

    pipeline.main(
        [
            "--data-repo-path",
            "/tmp/data",
            "--push",
            "--year",
            "2024",
            "--force",
            "--no-pdf-cache",
        ]
    )

    assert captured["data_repo_path"] == Path("/tmp/data")
    assert captured["year"] == 2024
    assert captured["push"] is True
    assert captured["force"] is True
    assert captured["use_pdf_cache"] is False
