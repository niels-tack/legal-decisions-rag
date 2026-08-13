"""MCP server exposing hosted Belgian Constitutional Court ruling search.

This is a local stdio MCP server: it runs on the end user's own machine
(started by their MCP client, e.g. Claude Desktop or Cursor) but never
performs any retrieval itself. Every tool call is proxied, server-side, to
the hosted query service (``src.query_service``) over HTTP, attaching the
shared API key from this process's environment. The key is read once per
call from ``SHARED_API_KEY`` and is never a tool parameter, so the MCP
client's user never sees or supplies it - satisfying the same "shared
static key, server-side only" requirement as the Copilot/Custom GPT
integration (see ``context/Technical requirements.md``).

Run directly with:

    uv run python -m src.mcp_server.server

which starts the server on the stdio transport, as expected by MCP clients
that launch servers as a subprocess.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

# Environment variables read server-side only; never accepted as tool
# parameters, so an MCP client's user can never see or override them.
QUERY_SERVICE_URL_ENV_VAR = "QUERY_SERVICE_URL"
SHARED_API_KEY_ENV_VAR = "SHARED_API_KEY"

API_KEY_HEADER = "X-API-Key"
SEARCH_PATH = "/search"
DEFAULT_LIMIT = 5
REQUEST_TIMEOUT_SECONDS = 10.0

mcp = MCPServer(
    "belgian-constitutional-court-search",
    instructions=(
        "Search Belgian Constitutional Court rulings (Dutch-language, POC "
        "scope) via a hosted hybrid BM25 + vector search API. Use "
        "search_constitutional_court_rulings to find cited passages for a "
        "plain-language legal question or an exact case/article lookup."
    ),
)


@mcp.tool()
async def search_constitutional_court_rulings(
    query: str, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """Search Belgian Constitutional Court rulings for relevant passages.

    Proxies to the hosted query service's ``GET /search`` endpoint, which
    runs hybrid BM25 + vector retrieval over the Court's Dutch-language
    rulings and returns ranked, cited passages. The shared API key is
    attached from this process's ``SHARED_API_KEY`` environment variable;
    callers of this tool never need to know or provide it.

    Args:
        query: The plain-language question or exact term to search for
            (e.g. a case number, article reference, or topical question).
        limit: Maximum number of ranked results to return.

    Returns:
        On success, the query service's parsed JSON response, e.g.
        ``{"query": ..., "results": [...]}``. On failure (missing server
        configuration, a non-200 response, or a network error), a dict of
        the form ``{"error": "<human-readable message>"}`` so the failure
        is surfaced through the tool result instead of raising and
        crashing the server process.
    """
    base_url = os.environ.get(QUERY_SERVICE_URL_ENV_VAR)
    api_key = os.environ.get(SHARED_API_KEY_ENV_VAR)
    if not base_url:
        return {
            "error": (
                f"Server misconfiguration: the {QUERY_SERVICE_URL_ENV_VAR} "
                "environment variable is not set."
            )
        }
    if not api_key:
        return {
            "error": (
                f"Server misconfiguration: the {SHARED_API_KEY_ENV_VAR} "
                "environment variable is not set."
            )
        }

    url = base_url.rstrip("/") + SEARCH_PATH
    params = {"q": query, "limit": limit}
    headers = {API_KEY_HEADER: api_key}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        return {"error": f"Network error contacting the query service: {exc}"}

    if response.status_code != httpx.codes.OK:
        return {
            "error": (
                f"Query service returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        }

    try:
        return response.json()
    except ValueError as exc:
        return {"error": f"Query service returned a non-JSON response: {exc}"}


if __name__ == "__main__":
    mcp.run()
