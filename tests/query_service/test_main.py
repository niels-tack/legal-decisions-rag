"""Integration tests for the query-service FastAPI app.

Uses the fixture ``TestClient`` from ``conftest.py``, which points the app
at a small fabricated ``cases.db`` and a fake embedding function so no real
model download is required.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.query_service.conftest import TEST_API_KEY


def test_health_requires_no_auth(client: TestClient) -> None:
    """``GET /health`` should succeed with no ``X-API-Key`` header at all."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_without_api_key_is_rejected(client: TestClient) -> None:
    """``GET /search`` without an ``X-API-Key`` header returns 401."""
    response = client.get("/search", params={"q": "milieu"})

    assert response.status_code == 401


def test_search_with_wrong_api_key_is_rejected(client: TestClient) -> None:
    """``GET /search`` with an incorrect key returns 401."""
    response = client.get(
        "/search",
        params={"q": "milieu"},
        headers={"X-API-Key": "not-the-right-key"},
    )

    assert response.status_code == 401


def test_search_with_valid_key_returns_matching_fixture(client: TestClient) -> None:
    """A query matching a known fixture passage is returned in ``results``."""
    response = client.get(
        "/search",
        params={"q": "milieuvergunning", "limit": 5},
        headers={"X-API-Key": TEST_API_KEY},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "milieuvergunning"
    assert body["results"], "expected at least one search result"

    top_result = body["results"][0]
    assert top_result["ecli"] == "ECLI:BE:GHCC:2025:ARR.001"
    assert top_result["case_number"] == "2025-001n"
    assert "omgevingsvergunning" in top_result["excerpt"].lower()
    assert top_result["score"] > 0


def test_search_with_blank_query_returns_400(client: TestClient) -> None:
    """A blank ``q`` parameter returns 400, not a 200 with empty results."""
    response = client.get(
        "/search",
        params={"q": "   "},
        headers={"X-API-Key": TEST_API_KEY},
    )

    assert response.status_code == 400


def test_search_missing_query_param_returns_400(client: TestClient) -> None:
    """An entirely missing ``q`` parameter also returns 400."""
    response = client.get("/search", headers={"X-API-Key": TEST_API_KEY})

    assert response.status_code == 400


def test_search_respects_limit(client: TestClient) -> None:
    """Requesting ``limit=1`` returns at most one result."""
    response = client.get(
        "/search",
        params={"q": "de", "limit": 1},
        headers={"X-API-Key": TEST_API_KEY},
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) <= 1
