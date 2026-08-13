"""Query service: the hosted hybrid-search HTTP API.

Serves ranked, cited passages from the ``cases.db`` artifact produced by
``src.indexing`` over HTTP, for consumption by Microsoft Copilot / Custom
GPT (OpenAPI action) and the MCP server. Kept independently testable from
ingestion and index-build per the project's module-separation constraint.
"""

from __future__ import annotations
