"""Static per-case page generation for the Phase 1 website.

Renders one self-contained HTML page per ruling (full text, metadata, link
to the original PDF) at build time, so the browser's search hot path never
needs to fetch ruling text out of ``cases.db`` - see
``context/Technical requirements.md``.
"""

from __future__ import annotations
