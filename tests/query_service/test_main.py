"""Integration tests for the query-service FastAPI app.

Uses the fixture ``TestClient`` from ``conftest.py``, which points the app
at a small fabricated ``cases.db`` and a fake embedding function so no real
model download is required. The service is keyless (no end-user or shared
client auth of any kind, per the technical requirements) - these tests
cover the actual abuse-protection surface instead: origin-locked CORS and
the query-parameter validation on ``/search``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.query_service.conftest import TEST_ALLOWED_ORIGIN


def test_health_succeeds(client: TestClient) -> None:
    """``GET /health`` should succeed with no auth of any kind."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_from_allowed_origin_returns_matching_fixture(
    client: TestClient,
) -> None:
    """A query matching a known fixture passage is returned in ``results``."""
    response = client.get(
        "/search",
        params={"q": "milieuvergunning", "limit": 5},
        headers={"Origin": TEST_ALLOWED_ORIGIN},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == TEST_ALLOWED_ORIGIN
    body = response.json()
    assert body["query"] == "milieuvergunning"
    assert body["results"], "expected at least one search result"

    top_result = body["results"][0]
    assert top_result["ecli"] == "ECLI:BE:GHCC:2025:ARR.001"
    assert top_result["case_number"] == "2025-001n"
    assert "omgevingsvergunning" in top_result["excerpt"].lower()
    assert top_result["score"] > 0


def test_search_preflight_from_disallowed_origin_is_rejected(
    client: TestClient,
) -> None:
    """A CORS preflight from an origin other than ALLOWED_ORIGIN is rejected."""
    response = client.options(
        "/search",
        headers={
            "Origin": "https://not-the-site.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_search_with_blank_query_returns_400(client: TestClient) -> None:
    """A blank ``q`` parameter returns 400, not a 200 with empty results."""
    response = client.get("/search", params={"q": "   "})

    assert response.status_code == 400


def test_search_missing_query_param_returns_400(client: TestClient) -> None:
    """An entirely missing ``q`` parameter also returns 400."""
    response = client.get("/search")

    assert response.status_code == 400


def test_search_sources_param_filters_results(client: TestClient) -> None:
    """The repeatable ``sources`` query param scopes results to that body."""
    response = client.get(
        "/search", params={"q": "verkeer", "sources": ["OTHER"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    assert all(result["source"] == "OTHER" for result in body["results"])


def test_search_respects_limit(client: TestClient) -> None:
    """Requesting ``limit=1`` returns at most one result."""
    response = client.get("/search", params={"q": "de", "limit": 1})

    assert response.status_code == 200
    assert len(response.json()["results"]) <= 1
