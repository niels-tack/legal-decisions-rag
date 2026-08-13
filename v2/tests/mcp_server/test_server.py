"""Tests for the Belgian Constitutional Court search MCP tool.

The HTTP call is never allowed to hit a real network: every test installs
an ``httpx.MockTransport`` in place of the transport a real
``httpx.AsyncClient`` would use, so the request-building code (URL, query
params, headers) runs for real while the wire itself is faked.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from src.mcp_server import server as mcp_server

QUERY_SERVICE_URL = "https://query.example.eu"
SHARED_API_KEY = "test-shared-key"


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Make every ``httpx.AsyncClient`` the server creates use ``handler``.

    Patches the ``httpx.AsyncClient`` symbol as seen from
    ``src.mcp_server.server`` so real request construction (URL joining,
    query-param encoding, header assembly) still runs, while the actual
    wire transport is replaced by a deterministic, offline fake.

    Args:
        monkeypatch: Pytest fixture used to scope the patch to one test.
        handler: Called with the outgoing ``httpx.Request``; must return
            the ``httpx.Response`` to hand back.
    """

    # Captured before patching: `httpx.AsyncClient` is looked up again below,
    # and by then the module attribute points at `fake_async_client` itself,
    # so calling through the live module name here would recurse forever.
    real_async_client = httpx.AsyncClient

    def fake_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", fake_async_client)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set both server-side env vars the tool needs to run at all."""
    monkeypatch.setenv(mcp_server.QUERY_SERVICE_URL_ENV_VAR, QUERY_SERVICE_URL)
    monkeypatch.setenv(mcp_server.SHARED_API_KEY_ENV_VAR, SHARED_API_KEY)


def test_missing_query_service_url_returns_error_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SHARED_API_KEY lookup, no HTTP call: a clear error dict instead."""
    monkeypatch.delenv(mcp_server.QUERY_SERVICE_URL_ENV_VAR, raising=False)
    monkeypatch.setenv(mcp_server.SHARED_API_KEY_ENV_VAR, SHARED_API_KEY)

    result = asyncio.run(
        mcp_server.search_constitutional_court_rulings(query="omgevingsvergunning")
    )

    assert "error" in result
    assert mcp_server.QUERY_SERVICE_URL_ENV_VAR in result["error"]


def test_missing_shared_api_key_returns_error_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing shared key must not be silently sent as an empty header."""
    monkeypatch.setenv(mcp_server.QUERY_SERVICE_URL_ENV_VAR, QUERY_SERVICE_URL)
    monkeypatch.delenv(mcp_server.SHARED_API_KEY_ENV_VAR, raising=False)

    result = asyncio.run(
        mcp_server.search_constitutional_court_rulings(query="omgevingsvergunning")
    )

    assert "error" in result
    assert mcp_server.SHARED_API_KEY_ENV_VAR in result["error"]


def test_sends_expected_url_query_params_and_api_key_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GET request must hit /search with q, limit, and X-API-Key set."""
    _set_required_env(monkeypatch)
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"query": "milieu", "results": []})

    _install_mock_transport(monkeypatch, handler)

    asyncio.run(mcp_server.search_constitutional_court_rulings(query="milieu", limit=7))

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "query.example.eu"
    assert request.url.path == "/search"
    assert dict(httpx.QueryParams(request.url.query)) == {
        "q": "milieu",
        "limit": "7",
    }
    assert request.headers[mcp_server.API_KEY_HEADER] == SHARED_API_KEY


def test_strips_trailing_slash_from_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A base URL with a trailing slash must not produce a double slash."""
    monkeypatch.setenv(mcp_server.QUERY_SERVICE_URL_ENV_VAR, QUERY_SERVICE_URL + "/")
    monkeypatch.setenv(mcp_server.SHARED_API_KEY_ENV_VAR, SHARED_API_KEY)
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"query": "x", "results": []})

    _install_mock_transport(monkeypatch, handler)

    asyncio.run(mcp_server.search_constitutional_court_rulings(query="x"))

    assert captured[0].url.path == "/search"


def test_successful_response_is_parsed_and_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 response's JSON body is returned unchanged as the tool result."""
    _set_required_env(monkeypatch)
    payload = {
        "query": "omgevingsvergunning",
        "results": [
            {
                "ecli": "ECLI:BE:GHCC:2025:ARR.001",
                "arrest_number": "1/2025",
                "role_number": "8001",
                "case_number": "2025-001n",
                "ruling_date": "2025-01-15",
                "language": "nl",
                "procedure_type": "Prejudiciele vraag",
                "controlled_norm": "Decreet omgevingsvergunning",
                "outcome": "Verwerping",
                "title": "Omgevingsvergunning milieu",
                "section": "reasoning",
                "excerpt": "De omgevingsvergunning voor milieu werd geweigerd.",
                "source_pdf_url": "https://nl.const-court.be/2025-001n.pdf",
                "score": 0.87,
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_mock_transport(monkeypatch, handler)

    result = asyncio.run(
        mcp_server.search_constitutional_court_rulings(query="omgevingsvergunning")
    )

    assert result == payload


def test_non_200_response_returns_error_message_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server-side failure must surface as a tool-result error, not raise."""
    _set_required_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    _install_mock_transport(monkeypatch, handler)

    result = asyncio.run(
        mcp_server.search_constitutional_court_rulings(query="omgevingsvergunning")
    )

    assert "error" in result
    assert "500" in result["error"]


def test_unauthorized_response_returns_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected shared key (401) must also come back as a clear error."""
    _set_required_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Missing or invalid API key."})

    _install_mock_transport(monkeypatch, handler)

    result = asyncio.run(
        mcp_server.search_constitutional_court_rulings(query="omgevingsvergunning")
    )

    assert "error" in result
    assert "401" in result["error"]


def test_network_error_returns_error_message_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection failure must not propagate as an unhandled exception."""
    _set_required_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_mock_transport(monkeypatch, handler)

    result = asyncio.run(
        mcp_server.search_constitutional_court_rulings(query="omgevingsvergunning")
    )

    assert "error" in result
    assert "connection refused" in result["error"].lower() or "network" in (
        result["error"].lower()
    )


def test_tool_is_registered_with_expected_name_and_default_limit() -> None:
    """The MCP server must advertise the tool under its documented name."""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}

    assert "search_constitutional_court_rulings" in names


def test_default_limit_is_sent_when_not_specified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting ``limit`` should fall back to the documented default."""
    _set_required_env(monkeypatch)
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"query": "x", "results": []})

    _install_mock_transport(monkeypatch, handler)

    asyncio.run(mcp_server.search_constitutional_court_rulings(query="x"))

    params = dict(httpx.QueryParams(captured[0].url.query))
    assert params["limit"] == str(mcp_server.DEFAULT_LIMIT)
