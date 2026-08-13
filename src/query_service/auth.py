"""Shared-key authentication for the query service's HTTP API.

Per the technical requirements, end users never hold a key: it is embedded
server-side in each client integration (the Copilot/Custom GPT OpenAPI
connector config, the MCP server's environment) and compared here using a
constant-time comparison to avoid leaking timing information about the
correct value.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status

API_KEY_ENV_VAR = "SHARED_API_KEY"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Validate the ``X-API-Key`` header against the ``SHARED_API_KEY`` env var.

    Args:
        x_api_key: The ``X-API-Key`` request header, injected by FastAPI.

    Raises:
        HTTPException: With status 401 if the header is missing, or if the
            ``SHARED_API_KEY`` environment variable is unset, or if the two
            values do not match.
    """
    expected = os.environ.get(API_KEY_ENV_VAR)
    if not x_api_key or not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
        )
