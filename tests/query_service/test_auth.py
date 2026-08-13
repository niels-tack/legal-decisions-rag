"""Unit tests for ``src.query_service.auth.require_api_key``.

Complements the end-to-end 401 checks in ``test_main.py`` by exercising the
dependency function directly, including the case where the server itself
has no ``SHARED_API_KEY`` configured.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from src.query_service.auth import require_api_key


def test_require_api_key_accepts_matching_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A header matching ``SHARED_API_KEY`` raises nothing."""
    monkeypatch.setenv("SHARED_API_KEY", "correct-key")

    require_api_key(x_api_key="correct-key")


def test_require_api_key_rejects_missing_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``None`` header (not sent at all) is rejected with 401."""
    monkeypatch.setenv("SHARED_API_KEY", "correct-key")

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key=None)

    assert exc_info.value.status_code == 401


def test_require_api_key_rejects_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A header present but not matching the shared secret is rejected."""
    monkeypatch.setenv("SHARED_API_KEY", "correct-key")

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key="wrong-key")

    assert exc_info.value.status_code == 401


def test_require_api_key_rejects_when_server_has_no_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``SHARED_API_KEY`` itself is unset, every request is rejected."""
    monkeypatch.delenv("SHARED_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key="anything")

    assert exc_info.value.status_code == 401
