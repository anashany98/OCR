"""Tests for the in-process embedding + reranker providers.

These tests mock ``sentence_transformers`` so they don't need a GPU
or a HuggingFace download. Integration tests that actually load
Granite 311M and BGE-reranker-v2-m3 live behind ``RUN_SLOW_AI_TESTS=1``.
"""
from __future__ import annotations

from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Install a fake ``sentence_transformers`` module so imports resolve
    without touching HuggingFace. The fake ``SentenceTransformer`` and
    ``CrossEncoder`` return MagicMocks that record calls."""
    fake = ModuleType("sentence_transformers")

    class _FakeModel:
        def __init__(self, *args, **kwargs):
            self.init_args = args
            self.init_kwargs = kwargs
            self.max_seq_length = None
            self.encode_calls: list = []
            self.predict_calls: list = []

        def encode(self, texts, **kwargs):
            self.encode_calls.append({"texts": list(texts), "kwargs": kwargs})
            # Return one normalized-looking vector per input text.
            import numpy as np

            return np.ones((len(texts), 4), dtype="float32")

        def predict(self, pairs, **kwargs):
            self.predict_calls.append({"pairs": list(pairs), "kwargs": kwargs})
            import numpy as np

            return np.ones(len(pairs), dtype="float32")

        def get_sentence_embedding_dimension(self):
            return 4

    fake.SentenceTransformer = _FakeModel
    fake.CrossEncoder = _FakeModel
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake)
    return fake


# ---------------------------------------------------------------------------
# Prompt handling
# ---------------------------------------------------------------------------


def test_granite_query_prompt_is_set():
    from app.services.embeddings import _query_prompt_for, _passage_prompt_for

    name = "ibm-granite/granite-embedding-311m-multilingual-r2"
    assert _query_prompt_for(name) == "query: "
    assert _passage_prompt_for(name) == "passage: "


def test_granite_family_all_use_asymmetric_prompts():
    """Any ibm-granite/granite-embedding-* model should get the
    query/passage prefix. The 311M is the one we ship, but the family
    is consistent."""
    from app.services.embeddings import _query_prompt_for

    for name in (
        "ibm-granite/granite-embedding-311m-multilingual-r2",
        "ibm-granite/granite-embedding-125m-english",
        "ibm-granite/granite-embedding-107m-multilingual",
    ):
        assert _query_prompt_for(name) == "query: "


def test_symmetric_model_gets_no_prompt():
    """BGE / E5 / most sentence-transformers models are symmetric and
    should not receive a prompt prefix."""
    from app.services.embeddings import _query_prompt_for, _passage_prompt_for

    for name in (
        "BAAI/bge-m3",
        "BAAI/bge-large-en-v1.5",
        "intfloat/e5-large-v2",
        "sentence-transformers/all-MiniLM-L6-v2",
    ):
        assert _query_prompt_for(name) is None
        assert _passage_prompt_for(name) is None


# ---------------------------------------------------------------------------
# Local embedding client
# ---------------------------------------------------------------------------


def test_local_client_is_lazy(fake_sentence_transformers, monkeypatch):
    """Constructing the client must NOT load the model — only the first
    encode call should. This is what keeps worker startup fast."""
    from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

    client = LocalSentenceTransformerEmbeddingClient(
        model_name="ibm-granite/granite-embedding-311m-multilingual-r2",
        device="cpu",
    )
    assert client._model is None
    client.embed_query("hola mundo")
    assert client._model is not None
    # Second call reuses the loaded model (no new init).
    client.embed_passage("adiós mundo")
    assert len(client._model.init_args) >= 1


def test_local_client_uses_asymmetric_prompts(fake_sentence_transformers):
    from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

    client = LocalSentenceTransformerEmbeddingClient(
        model_name="ibm-granite/granite-embedding-311m-multilingual-r2",
        device="cpu",
    )
    client.embed_query("¿Cuánto es el total?")
    encode_call = client._model.encode_calls[0]
    assert encode_call["kwargs"]["prompt"] == "query: "

    client.embed_passage("Total factura: 1.234,56 euros")
    encode_call = client._model.encode_calls[1]
    assert encode_call["kwargs"]["prompt"] == "passage: "


def test_local_client_omits_prompt_for_symmetric_models(fake_sentence_transformers):
    from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

    client = LocalSentenceTransformerEmbeddingClient(
        model_name="BAAI/bge-m3",
        device="cpu",
    )
    client.embed_query("test")
    encode_call = client._model.encode_calls[0]
    assert "prompt" not in encode_call["kwargs"]


def test_local_client_dimensions(fake_sentence_transformers):
    from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

    client = LocalSentenceTransformerEmbeddingClient(
        model_name="ibm-granite/granite-embedding-311m-multilingual-r2",
        device="cpu",
    )
    assert client.dimensions == 4  # the fake model reports 4


def test_local_client_singleton_caches_by_model_and_device(monkeypatch, fake_sentence_transformers):
    """Two calls to get_local_embedding_client with the same model+device
    should return the same instance. The underlying SentenceTransformer
    is loaded lazily on the first encode call and reused afterwards."""
    from app.services import embeddings

    embeddings._local_embedding_clients.clear()
    monkeypatch.setattr(settings, "embedding_local_model", "ibm-granite/granite-embedding-311m-multilingual-r2")
    monkeypatch.setattr(settings, "embedding_local_device", "cpu")
    monkeypatch.setattr(settings, "embedding_local_batch_size", 8)
    monkeypatch.setattr(settings, "embedding_local_max_length", 256)

    a = embeddings.get_local_embedding_client()
    b = embeddings.get_local_embedding_client()
    assert a is b
    # No encode yet — the model is lazy, so it must not be loaded.
    assert a._model is None
    # First encode triggers the load.
    a.embed_query("hola")
    assert a._model is not None
    # Second encode reuses the same loaded model (no new init).
    a.embed_passage("adiós")
    assert a._model is b._model


# ---------------------------------------------------------------------------
# Batch generation wiring
# ---------------------------------------------------------------------------


def test_batch_generation_uses_local_client_when_provider_set(monkeypatch, fake_sentence_transformers):
    """``_generate_embeddings_batch`` with provider='local_sentence_transformers'
    must hit the in-process client, not the OpenAI-compatible path or the
    hash fallback."""
    from app.services import embeddings

    embeddings._local_embedding_clients.clear()
    monkeypatch.setattr(settings, "embedding_local_model", "ibm-granite/granite-embedding-311m-multilingual-r2")
    monkeypatch.setattr(settings, "embedding_local_device", "cpu")

    out = embeddings._generate_embeddings_batch(
        ["hola", "adiós"], provider="local_sentence_transformers", dimensions=4
    )
    assert len(out) == 2
    assert all(len(v) == 4 for v in out)


def test_batch_generation_falls_back_to_hash_on_local_failure(monkeypatch):
    """If the local model fails to load, fall back to the hash embeddings
    so the pipeline keeps running (matches the existing OpenAI-compatible
    fallback behaviour)."""
    from app.services import embeddings

    # Force the local client to raise on first encode.
    class _BoomClient:
        def embed_many(self, texts):
            raise RuntimeError("model not loaded")

    monkeypatch.setattr(embeddings, "get_local_embedding_client", lambda: _BoomClient())
    monkeypatch.setattr(settings, "embedding_fallback_to_hash", True)

    out = embeddings._generate_embeddings_batch(
        ["hola"], provider="local_sentence_transformers", dimensions=4
    )
    assert len(out) == 1
    assert len(out[0]) == 4


# ---------------------------------------------------------------------------
# Local reranker
# ---------------------------------------------------------------------------


def test_local_reranker_scores_pairs(fake_sentence_transformers):
    from app.services.reranker import LocalSentenceTransformerReranker

    reranker = LocalSentenceTransformerReranker(
        model_name="BAAI/bge-reranker-v2-m3", device="cpu", max_length=256
    )
    scores = reranker.score("¿Cuál es el total?", ["Total: 1.234 €", "Color favorito: azul"])
    assert len(scores) == 2
    assert all(isinstance(s, float) for s in scores)


def test_local_reranker_is_lazy(fake_sentence_transformers):
    from app.services.reranker import LocalSentenceTransformerReranker

    reranker = LocalSentenceTransformerReranker(
        model_name="BAAI/bge-reranker-v2-m3", device="cpu", max_length=256
    )
    assert reranker._model is None
    reranker.score("q", ["d"])
    assert reranker._model is not None


def test_rerank_function_uses_local_path_when_configured(monkeypatch, fake_sentence_transformers):
    """When ``reranker_local_model`` is set, the async ``rerank()`` must
    hit the in-process CrossEncoder and not the HTTP endpoint."""
    import asyncio

    from app.services import reranker

    # Reset the local reranker singleton so the new device/model take.
    reranker._local_reranker = None
    monkeypatch.setattr(settings, "reranker_local_model", "BAAI/bge-reranker-v2-m3")
    monkeypatch.setattr(settings, "reranker_local_device", "cpu")

    # Build a SearchResult-ish object with the fields the reranker reads.
    from app.services.search_service import SearchResult

    candidates = [
        SearchResult(
            document_id=1,
            original_filename="doc.pdf",
            document_type="invoice",
            status="processed",
            page_number=1,
            block_id=None,
            score=0.5,
            excerpt="Total: 1.234,56 euros",
            ocr_confidence=0.9,
            source_type="text",
        )
        for _ in range(6)
    ]

    out = asyncio.run(reranker.rerank("¿Cuál es el total?", candidates, top_k=3))
    assert len(out) == 3
    # All scores should be the fake's constant 1.0, rounded.
    assert all(abs(r.score - 1.0) < 1e-6 for r in out)


def test_rerank_function_falls_back_to_original_order_on_local_failure(monkeypatch, fake_sentence_transformers):
    """If the local reranker raises (e.g. OOM), the function returns the
    top_k candidates in their original order — search must not break."""
    import asyncio

    from app.services import reranker
    from app.services.search_service import SearchResult

    def _boom(*args, **kwargs):
        raise RuntimeError("GPU OOM")

    monkeypatch.setattr(reranker, "get_local_reranker", _boom)
    monkeypatch.setattr(settings, "reranker_local_model", "BAAI/bge-reranker-v2-m3")
    reranker._local_reranker = None

    candidates = [
        SearchResult(
            document_id=i + 1,
            original_filename=f"doc{i}.pdf",
            document_type="invoice",
            status="processed",
            page_number=1,
            block_id=None,
            score=0.5,
            excerpt=f"excerpt {i}",
            ocr_confidence=0.9,
            source_type="text",
        )
        for i in range(6)
    ]
    out = asyncio.run(reranker.rerank("query", candidates, top_k=3))
    # Original order preserved: doc 1, 2, 3.
    assert [r.document_id for r in out] == [1, 2, 3]


def test_rerank_skips_when_too_few_candidates(fake_sentence_transformers):
    """The reranker is pointless for <5 candidates (it's a precision
    booster on already-shortlisted hits). Returns the original prefix."""
    import asyncio

    from app.services import reranker
    from app.services.search_service import SearchResult

    candidates = [
        SearchResult(
            document_id=1,
            original_filename="doc.pdf",
            document_type="invoice",
            status="processed",
            page_number=1,
            block_id=None,
            score=0.5,
            excerpt="text",
            ocr_confidence=0.9,
            source_type="text",
        )
    ]
    out = asyncio.run(reranker.rerank("q", candidates, top_k=5))
    assert out == candidates[:5]
    # The local model should not have been touched.
    assert reranker._local_reranker is None
