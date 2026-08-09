"""Index-build pipeline: turns committed ruling Markdown into ``cases.db``.

This package is independently testable from ingestion (which produces the
Markdown) and the query service (which reads the resulting SQLite file), per
the project's separation-of-concerns constraint.
"""

from __future__ import annotations
