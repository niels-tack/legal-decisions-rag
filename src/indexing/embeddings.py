"""Sentence-embedding computation for the hybrid search index.

Loads the multilingual sentence-transformers model named in
``src.db_schema.EMBEDDING_MODEL_NAME`` once per process and reuses it for
every call. Vectors are L2-normalized so that a dot product between two
embeddings equals their cosine similarity, letting the query service skip a
separate normalization step at retrieval time.

**Prefix discipline**: ``intfloat/multilingual-e5-small`` (and the whole
E5 family) requires exact prefix strings prepended to every text before
encoding. Omitting them silently degrades retrieval quality. Use
``embed_passages`` for index-time chunk encoding and import
``EMBEDDING_QUERY_PREFIX`` from ``src.db_schema`` to prefix queries at
retrieval time - both callers must use the matching constants from that
module.
"""

from __future__ import annotations

import numpy as np

from src.db_schema import EMBEDDING_MODEL_NAME, EMBEDDING_PASSAGE_PREFIX

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
    """Embed a batch of texts with the shared multilingual model, no prefix.

    Low-level function. Most callers should use ``embed_passages`` (index
    time) or apply ``EMBEDDING_QUERY_PREFIX`` themselves (query time) rather
    than calling this directly.

    Args:
        texts: Already-prefixed strings to embed. May be empty.

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


def embed_passages(texts: list[str]) -> np.ndarray:
    """Embed passage texts for index storage, applying the required passage prefix.

    Use this as the ``embed_fn`` for ``build_index.add_embeddings``. The
    ``"passage: "`` prefix is mandatory for E5-class models; using bare text
    silently degrades retrieval quality.

    Args:
        texts: Plain passage texts (without any prefix). May be empty.

    Returns:
        A ``(len(texts), dim)`` float32 array of L2-normalized embeddings.
        Returns an empty ``(0, 0)`` array when ``texts`` is empty.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    prefixed = [EMBEDDING_PASSAGE_PREFIX + t for t in texts]
    return embed_texts(prefixed)


# Expose model_name as a function attribute so build_index.add_embeddings can
# read it without importing the constant separately.
embed_passages.model_name = EMBEDDING_MODEL_NAME  # type: ignore[attr-defined]
