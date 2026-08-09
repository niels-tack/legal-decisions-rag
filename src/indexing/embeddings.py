"""Sentence-embedding computation for the hybrid search index.

Loads the multilingual sentence-transformers model named in
``src.db_schema.EMBEDDING_MODEL_NAME`` once per process and reuses it for
every call. Vectors are L2-normalized so that a dot product between two
embeddings equals their cosine similarity, letting the query service skip a
separate normalization step at retrieval time.
"""

from __future__ import annotations

import numpy as np

from src.db_schema import EMBEDDING_MODEL_NAME

# Populated lazily by _get_model(); module-level so the (large) model is
# loaded at most once per process instead of once per embed_texts() call.
_model = None


def _get_model():  # noqa: ANN202 - returns a third-party SentenceTransformer
    """Return the cached ``SentenceTransformer`` model, loading it on first use.

    The import is deferred to inside this function (rather than at module
    scope) so that importing ``src.indexing.embeddings`` stays cheap for
    callers - such as ``build_index`` under test - that inject a fake
    ``embed_fn`` and never actually need ``sentence-transformers`` installed.

    Returns:
        The loaded ``SentenceTransformer`` instance for ``EMBEDDING_MODEL_NAME``.
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts with the shared multilingual model.

    Args:
        texts: Passage or query strings to embed. May be empty.

    Returns:
        A ``(len(texts), dim)`` float32 array of L2-normalized embeddings,
        so that cosine similarity between rows reduces to a plain dot
        product. Returns an empty ``(0, 0)`` array when ``texts`` is empty.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    model = _get_model()
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.astype(np.float32)
