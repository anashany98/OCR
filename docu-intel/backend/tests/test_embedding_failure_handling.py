"""Tests for the embedding pipeline's failure handling.

When the embedding provider fails (e.g. local model can't load on a
CPU worker, or the OpenAI-compatible endpoint is down), the document
should still be stored — the chunks get ``embedding=None`` and
``needs_reembedding=True`` so an admin can re-trigger embedding
later. The user explicitly asked for this behaviour: "pues que el
documento se quede sin embedding".
"""
from __future__ import annotations

# The embedding pipeline imports ``embed_many`` and
# ``should_create_embeddings`` directly from ``app.services.embeddings``
# since the ``_facade()`` antipattern was removed. The tests
# therefore patch the symbols on the module that defines them
# (``app.services.embeddings``) rather than on the historical
# re-export hub (``app.services.document_service``). The hub is still
# imported for side effect: other tests in the suite exercise
# the public facade and rely on it being importable.
from app.services import document_service  # noqa: F401  (imported for side effect)
from unittest.mock import patch

import pytest

from app.services.embeddings import EmbeddingProviderError


def test_embed_many_with_metadata_swallows_provider_error():
    """An ``EmbeddingProviderError`` from the underlying provider must
    not propagate — the caller gets ``(None, "failed", True)`` for
    every text so the chunks can be stored without an embedding."""
    from app.services.document_embedding_pipeline import embed_many_with_metadata

    with patch(
            "app.services.document_embedding_pipeline.embed_many",side_effect=EmbeddingProviderError("boom"),
    ):
        out = embed_many_with_metadata(["chunk a", "chunk b", "chunk c"])

    assert out == [
        (None, "failed", True),
        (None, "failed", True),
        (None, "failed", True),
    ]


def test_embed_many_with_metadata_swallows_unexpected_errors():
    """Any other exception in the embedding path is also swallowed so
    the document survives — we never want a transient encoder bug to
    lose the OCR work too."""
    from app.services.document_embedding_pipeline import embed_many_with_metadata

    with patch(
            "app.services.document_embedding_pipeline.embed_many",side_effect=RuntimeError("GPU OOM"),
    ):
        out = embed_many_with_metadata(["chunk a"])

    assert out == [(None, "failed", True)]


def test_embed_many_with_metadata_empty_input():
    from app.services.document_embedding_pipeline import embed_many_with_metadata

    assert embed_many_with_metadata([]) == []


def test_embed_many_with_metadata_passes_through_on_success():
    """Happy path: when the embedding call works, we get the vectors
    plus the configured provider label and the fallback flag."""
    from app.services.document_embedding_pipeline import embed_many_with_metadata

    with patch("app.services.document_embedding_pipeline.embed_many", return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    ):
        out = embed_many_with_metadata(["a", "b"])

    assert out[0][0] == [0.1, 0.2, 0.3]
    assert out[0][2] is False  # not a fallback
    assert out[1][0] == [0.4, 0.5, 0.6]


def test_prepare_document_chunks_stores_unembedded_when_provider_fails():
    """End-to-end: a document processed while the embedding provider is
    down should land with ``embedding=None`` and
    ``needs_reembedding=True``. The text and OCR work are preserved."""
    from app.services.document_embedding_pipeline import prepare_document_chunks

    page_texts = [
        (1, "Primera página del documento. Tiene suficiente texto para chunking serio."),
    ]

    with patch(
            "app.services.document_embedding_pipeline.embed_many",side_effect=EmbeddingProviderError("model not loaded"),
    ), patch("app.services.document_embedding_pipeline.should_create_embeddings", return_value=True):
        chunks = prepare_document_chunks(document_id=42, page_texts=page_texts)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.document_id == 42
        assert chunk.embedding is None
        assert chunk.needs_reembedding is True
        assert chunk.embedding_provider_used == "failed"
        assert chunk.embedding_fallback is True
        # The text itself is preserved — OCR work is not lost.
        assert chunk.chunk_text
        assert chunk.token_count > 0


def test_prepare_document_chunks_embeds_metadata_header_without_polluting_chunk_text():
    from app.services.document_embedding_pipeline import prepare_document_chunks

    embedded_texts: list[str] = []

    def fake_embed_many(texts: list[str]) -> list[list[float]]:
        embedded_texts.extend(texts)
        return [[0.1] * 1024 for _ in texts]

    page_texts = [(2, "Total factura 120 euros. Base imponible 100 euros.")]

    with (
        patch("app.services.document_embedding_pipeline.embed_many", side_effect=fake_embed_many),
        patch(
            "app.services.document_embedding_pipeline.should_create_embeddings",return_value=True,
        ),
    ):
        chunks = prepare_document_chunks(
            document_id=42,
            page_texts=page_texts,
            document_type="factura",
            original_filename="2024_0345.pdf",
        )

    assert chunks[0].chunk_text == "Total factura 120 euros. Base imponible 100 euros."
    assert embedded_texts == [
        "[tipo=factura | fichero=2024_0345.pdf | pág=2] "
        "Total factura 120 euros. Base imponible 100 euros."
    ]
