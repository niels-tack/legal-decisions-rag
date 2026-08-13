"""Shared fixtures for the query-service test suite.

Builds a small, fully fabricated ``cases.db`` using the real
``src.db_schema`` helpers (rather than mocking SQLite) so the tests exercise
the exact schema the production index builder produces, then wires it up to
a FastAPI ``TestClient`` with a fake, deterministic embedding function so no
test needs to download the real sentence-transformers model.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from src.db_schema import initialize_database, insert_passage

TEST_API_KEY = "test-shared-key"

# Small fixed-dimension vectors so the fake embedder never needs the real
# model. Deliberately distinct per fixture passage so semantic ranking has
# something meaningful to discriminate on.
_EMBEDDING_DIM = 4
_FIXTURE_VECTORS = {
    "environment": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
    "pension": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
    "tax": np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32),
}

# Fabricated passages: (case row index, section, text, embedding key).
_FIXTURE_PASSAGES = [
    (
        0,
        "reasoning",
        "De omgevingsvergunning voor milieu werd geweigerd.",
        "environment",
    ),
    (1, "reasoning", "Het pensioenstelsel voor sociale zekerheid wijzigt.", "pension"),
    (2, "reasoning", "De fiscale controle op belastingen was onrechtmatig.", "tax"),
]

_FIXTURE_CASES = [
    {
        "ecli": "ECLI:BE:GHCC:2025:ARR.001",
        "arrest_number": "1/2025",
        "role_number": "8001",
        "file_slug": "2025-001n",
        "ruling_date": "2025-01-15",
        "language": "nl",
        "procedure_type": "Prejudiciele vraag",
        "controlled_norm": "Decreet omgevingsvergunning",
        "outcome": "Verwerping",
        "keywords": "[]",
        "source_pdf_url": "https://nl.const-court.be/2025-001n.pdf",
        "title": "Omgevingsvergunning milieu",
    },
    {
        "ecli": "ECLI:BE:GHCC:2025:ARR.002",
        "arrest_number": "2/2025",
        "role_number": "8002",
        "file_slug": "2025-002n",
        "ruling_date": "2025-02-20",
        "language": "nl",
        "procedure_type": "Beroep tot vernietiging",
        "controlled_norm": "Wet sociale zekerheid",
        "outcome": "Vernietiging",
        "keywords": "[]",
        "source_pdf_url": "https://nl.const-court.be/2025-002n.pdf",
        "title": "Pensioenstelsel",
    },
    {
        "ecli": "ECLI:BE:GHCC:2025:ARR.003",
        "arrest_number": "3/2025",
        "role_number": "8003",
        "file_slug": "2025-003n",
        "ruling_date": "2025-03-05",
        "language": "nl",
        "procedure_type": "Prejudiciele vraag",
        "controlled_norm": "Wetboek inkomstenbelastingen",
        "outcome": "Verwerping",
        "keywords": "[]",
        "source_pdf_url": "https://nl.const-court.be/2025-003n.pdf",
        "title": "Fiscale controle",
    },
]


def fake_embed_fn(texts: list[str]) -> np.ndarray:
    """Deterministically embed text without loading a real model.

    Maps a query to the fixture vector whose keyword it contains, falling
    back to a zero vector for anything unrecognized so semantic scores for
    unrelated fixtures stay at zero rather than raising.

    Args:
        texts: Texts to embed (only the query, one at a time, in practice).

    Returns:
        A ``(len(texts), 4)`` float32 array.
    """
    vectors = []
    for text in texts:
        lowered = text.lower()
        if "milieu" in lowered or "omgevingsvergunning" in lowered:
            vectors.append(_FIXTURE_VECTORS["environment"])
        elif "pensioen" in lowered:
            vectors.append(_FIXTURE_VECTORS["pension"])
        elif "fiscale" in lowered or "belasting" in lowered:
            vectors.append(_FIXTURE_VECTORS["tax"])
        else:
            vectors.append(np.zeros(_EMBEDDING_DIM, dtype=np.float32))
    return np.stack(vectors).astype(np.float32)


def _build_fixture_db(db_path: Path) -> None:
    """Create and populate a fixture ``cases.db`` at ``db_path``.

    Args:
        db_path: Destination path for the new SQLite file (must not exist).
    """
    conn = sqlite3.connect(str(db_path))
    initialize_database(conn)

    for case_id, case in enumerate(_FIXTURE_CASES, start=1):
        conn.execute(
            "INSERT INTO cases (case_id, ecli, arrest_number, role_number, "
            "file_slug, ruling_date, language, procedure_type, "
            "controlled_norm, outcome, keywords, source_pdf_url, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                case["ecli"],
                case["arrest_number"],
                case["role_number"],
                case["file_slug"],
                case["ruling_date"],
                case["language"],
                case["procedure_type"],
                case["controlled_norm"],
                case["outcome"],
                case["keywords"],
                case["source_pdf_url"],
                case["title"],
            ),
        )

    for passage_id, (case_index, section, text, embedding_key) in enumerate(
        _FIXTURE_PASSAGES, start=1
    ):
        case_id = case_index + 1
        insert_passage(conn, passage_id, case_id, section, text)
        vector = _FIXTURE_VECTORS[embedding_key]
        conn.execute(
            "INSERT INTO passage_embeddings "
            "(passage_id, case_id, section, text, model_name, vector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (passage_id, case_id, section, text, "fake-test-model", vector.tobytes()),
        )

    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db_path(tmp_path: Path) -> Path:
    """Build a fixture ``cases.db`` in a pytest temp directory.

    Args:
        tmp_path: Pytest-provided per-test temporary directory.

    Returns:
        Path to the populated SQLite file.
    """
    db_path = tmp_path / "cases.db"
    _build_fixture_db(db_path)
    return db_path


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, fixture_db_path: Path
) -> Iterator[TestClient]:
    """A ``TestClient`` wired to the fixture database and a fake embedder.

    Sets ``CASES_DB_PATH`` (so the app's lifespan opens the fixture file
    instead of downloading anything) and ``SHARED_API_KEY`` before the app
    starts, and overrides the embedding dependency so no real model loads.

    Args:
        monkeypatch: Pytest fixture for scoped environment variable changes.
        fixture_db_path: Path to the fixture database built above.

    Yields:
        A ``TestClient`` for the query-service FastAPI app.
    """
    monkeypatch.setenv("CASES_DB_PATH", str(fixture_db_path))
    monkeypatch.delenv("CASES_DB_URL", raising=False)
    monkeypatch.setenv("SHARED_API_KEY", TEST_API_KEY)

    # Imported after env vars are set and fresh per test so module-level
    # `app` state (dependency overrides) doesn't leak between tests.
    from src.query_service import main as query_service_main

    query_service_main.app.dependency_overrides[query_service_main.get_embed_fn] = (
        lambda: fake_embed_fn
    )

    with TestClient(query_service_main.app) as test_client:
        yield test_client

    query_service_main.app.dependency_overrides.clear()
