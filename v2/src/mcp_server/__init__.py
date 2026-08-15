"""MCP server package.

Exposes the hosted Belgian Constitutional Court ruling search API as an MCP
tool for Claude Desktop, Cursor, and VS Code Copilot. This package holds no
retrieval logic of its own - it is a thin, server-side authenticated proxy
onto the same hosted query service (``src.query_service``) that the
Copilot/Custom GPT integration calls, so the shared API key never has to
leave the maintainer's infrastructure or be entered by an end user.
"""

from __future__ import annotations
