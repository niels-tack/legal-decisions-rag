"""Tests for src.indexing.embeddings.

The real sentence-transformers model is never loaded here (slow, network
heavy); instead a fake model is monkeypatched in via ``_get_model`` so the
wrapping logic (dtype, empty-input handling, singleton caching) can be
verified in isolation.
"""

from __future__ import annotations

import numpy as np
import pytest
from src.indexing import embeddings


class _FakeModel:
    """Stand-in for ``SentenceTransformer`` that records call arguments."""

    def __init__(self) -> None:
        self.encode_calls: list[list[str]] = []

    def encode(
        self,
        texts: list[str],
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        self.encode_calls.append(texts)
        # Return float64 on purpose to verify embed_texts casts to float32.
        return np.ones((len(texts), 4), dtype=np.float64)


@pytest.fixture(autouse=True)
def _reset_model_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with a clean, unloaded model singleton."""
    monkeypatch.setattr(embeddings, "_model", None)


def test_embed_texts_returns_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_texts must cast the model's output to float32."""
    fake_model = _FakeModel()
    monkeypatch.setattr(embeddings, "_get_model", lambda: fake_model)

    result = embeddings.embed_texts(["hello", "world"])

    assert result.dtype == np.float32
    assert result.shape == (2, 4)


def test_embed_texts_empty_input_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty text list should not touch the model at all."""
    fake_model = _FakeModel()
    monkeypatch.setattr(embeddings, "_get_model", lambda: fake_model)

    result = embeddings.embed_texts([])

    assert result.shape == (0, 0)
    assert fake_model.encode_calls == []


def test_model_is_loaded_lazily_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_model should construct the model once and reuse it thereafter."""
    # Requires the (heavy) sentence-transformers package to be importable,
    # but never downloads or constructs the real model - the constructor
    # itself is monkeypatched below. Skips cleanly if the package isn't
    # installed in the environment running these tests.
    sentence_transformers = pytest.importorskip("sentence_transformers")

    load_count = 0
    fake_model = _FakeModel()

    def fake_constructor(_model_name: str) -> _FakeModel:
        nonlocal load_count
        load_count += 1
        return fake_model

    # Patch the name SentenceTransformer is imported under inside _get_model
    # by patching the sentence_transformers module's attribute it looks up.
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_constructor)

    first = embeddings._get_model()
    second = embeddings._get_model()

    assert load_count == 1
    assert first is second is fake_model
