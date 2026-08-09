"""Local ingestion pipeline: discover, extract, assemble, and publish rulings.

Three independently testable concerns, kept in separate modules per the
project's technical requirements:

- ``discover``: scrape the Court's case overview listing for per-ruling
  metadata and PDF URLs.
- ``extract``: convert a ruling PDF into clean text, split into the four
  structural sections shared via ``src.schemas``.
- ``assemble``: render a ``CaseMetadata`` instance plus section text into
  the Markdown file format consumed by ``src.indexing``.

``pipeline`` wires the three together into the weekly, offline scrape-and
-publish job that runs on the maintainer's own hardware.
"""
