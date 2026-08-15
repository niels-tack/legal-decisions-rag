"""Tests for the cases.db download logic in src.query_service.main.

Covers the private-bucket (boto3) path added on top of the original
plain-URL fallback, without making any real network or AWS/Scaleway calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.query_service import main as query_service_main


def test_ensure_cases_db_skips_download_if_file_exists(tmp_path: Path) -> None:
    """No download of any kind is attempted if the db already exists."""
    db_path = tmp_path / "cases.db"
    db_path.write_bytes(b"already here")

    with patch("boto3.client") as mock_boto_client:
        asyncio.run(query_service_main._ensure_cases_db(db_path))

    mock_boto_client.assert_not_called()
    assert db_path.read_bytes() == b"already here"


def test_ensure_cases_db_prefers_private_bucket_over_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When CASES_BUCKET_NAME is set, the boto3 path is used, not CASES_DB_URL."""
    db_path = tmp_path / "cases.db"
    monkeypatch.setenv(query_service_main.CASES_BUCKET_NAME_ENV_VAR, "my-bucket")
    monkeypatch.setenv(query_service_main.CASES_BUCKET_REGION_ENV_VAR, "fr-par")
    monkeypatch.setenv(
        query_service_main.CASES_BUCKET_ENDPOINT_ENV_VAR,
        "https://s3.fr-par.scw.cloud",
    )
    monkeypatch.setenv(query_service_main.CASES_BUCKET_ACCESS_KEY_ENV_VAR, "ak")
    monkeypatch.setenv(query_service_main.CASES_BUCKET_SECRET_KEY_ENV_VAR, "sk")
    monkeypatch.setenv(
        query_service_main.CASES_DB_URL_ENV_VAR, "https://example.com/cases.db"
    )

    mock_s3 = MagicMock()

    def fake_download_file(bucket: str, key: str, filename: str) -> None:
        assert bucket == "my-bucket"
        assert key == query_service_main.CASES_DB_OBJECT_KEY
        Path(filename).write_bytes(b"from bucket")

    mock_s3.download_file.side_effect = fake_download_file

    with patch("boto3.client", return_value=mock_s3) as mock_boto_client:
        asyncio.run(query_service_main._ensure_cases_db(db_path))

    mock_boto_client.assert_called_once_with(
        "s3",
        region_name="fr-par",
        endpoint_url="https://s3.fr-par.scw.cloud",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    assert db_path.read_bytes() == b"from bucket"


def test_ensure_cases_db_falls_back_to_url_without_bucket_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no CASES_BUCKET_NAME set, the plain HTTP(S) URL path still works."""
    db_path = tmp_path / "cases.db"
    monkeypatch.delenv(query_service_main.CASES_BUCKET_NAME_ENV_VAR, raising=False)
    monkeypatch.setenv(
        query_service_main.CASES_DB_URL_ENV_VAR, "https://example.com/cases.db"
    )

    class _FakeResponse:
        content = b"from url"

        def raise_for_status(self) -> None:
            return None

    class _FakeAsyncClient:
        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        async def get(self, url: str, follow_redirects: bool = True) -> _FakeResponse:
            assert url == "https://example.com/cases.db"
            return _FakeResponse()

    with patch.object(query_service_main.httpx, "AsyncClient", _FakeAsyncClient):
        asyncio.run(query_service_main._ensure_cases_db(db_path))

    assert db_path.read_bytes() == b"from url"


def test_ensure_cases_db_noop_without_any_source_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With neither the bucket nor the URL env var set, nothing is downloaded."""
    db_path = tmp_path / "cases.db"
    monkeypatch.delenv(query_service_main.CASES_BUCKET_NAME_ENV_VAR, raising=False)
    monkeypatch.delenv(query_service_main.CASES_DB_URL_ENV_VAR, raising=False)

    with patch("boto3.client") as mock_boto_client:
        asyncio.run(query_service_main._ensure_cases_db(db_path))

    mock_boto_client.assert_not_called()
    assert not db_path.exists()
