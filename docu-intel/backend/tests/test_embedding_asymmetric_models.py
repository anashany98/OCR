"""
Unit tests for EMB-PROV-1 (Sprint 2).

The previous implementation of ``_query_prompt_for`` /
``_passage_prompt_for`` used a broad ``startswith`` heuristic
that matched any model whose name started with
``"ibm-granite/granite-embedding"``. This was a footgun: a
future symmetric model with such a prefix would silently
receive the IBM Granite prefix and produce lower-quality
embeddings without any warning.

The new code uses the explicit :data:`_ASYMMETRIC_MODELS`
allow-list only. These tests verify the behaviour:

1. Listed models still get the prefix.
2. Unlisted models (including those with a matching prefix)
   do NOT get the prefix.
3. The list is exact, not fuzzy.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


class TestAsymmetricModelWhitelist:
    """The whitelist is exact."""

    def test_granite_311m_listed(self):
        from app.services.embeddings import _ASYMMETRIC_MODELS

        assert "ibm-granite/granite-embedding-311m-multilingual-r2" in _ASYMMETRIC_MODELS

    def test_granite_125m_english_listed(self):
        from app.services.embeddings import _ASYMMETRIC_MODELS

        assert "ibm-granite/granite-embedding-125m-english" in _ASYMMETRIC_MODELS

    def test_granite_107m_listed(self):
        from app.services.embeddings import _ASYMMETRIC_MODELS

        assert "ibm-granite/granite-embedding-107m-multilingual" in _ASYMMETRIC_MODELS


class TestQueryPromptFor:
    """``_query_prompt_for`` returns the query prefix for listed
    asymmetric models, ``None`` for anything else.
    """

    def test_listed_granite_311m_gets_prefix(self):
        from app.services.embeddings import (
            _GRANITE_QUERY_PROMPT,
            _query_prompt_for,
        )

        assert (
            _query_prompt_for("ibm-granite/granite-embedding-311m-multilingual-r2")
            == _GRANITE_QUERY_PROMPT
        )

    def test_listed_granite_125m_gets_prefix(self):
        from app.services.embeddings import (
            _GRANITE_QUERY_PROMPT,
            _query_prompt_for,
        )

        assert (
            _query_prompt_for("ibm-granite/granite-embedding-125m-english")
            == _GRANITE_QUERY_PROMPT
        )

    def test_bge_m3_returns_none(self):
        """BGE-M3 is a SYMMETRIC model. The legacy heuristic
        (prefix-match on ``ibm-granite/granite-embedding``)
        never matched it, so it should still return None.
        """
        from app.services.embeddings import _query_prompt_for

        assert _query_prompt_for("BAAI/bge-m3") is None

    def test_e5_returns_none(self):
        """E5 models are symmetric."""
        from app.services.embeddings import _query_prompt_for

        assert _query_prompt_for("intfloat/e5-large-v2") is None

    def test_unlisted_granite_prefix_match_returns_none(self):
        """EMB-PROV-1 fix: a model that ``startswith`` the IBM
        Granite prefix but is NOT in the allow-list must NOT
        receive the prefix. This is the regression the audit
        called out.
        """
        from app.services.embeddings import _query_prompt_for

        # Hypothetical future model with a similar prefix but
        # with a different (or no) prompt contract.
        assert _query_prompt_for("ibm-granite/granite-embedding-2b-v2") is None
        assert _query_prompt_for("ibm-granite/granite-embedding-experimental") is None
        # Even a completely different model that happens to
        # start with the same literal — must not match.
        assert _query_prompt_for("ibm-granite/granite-embedding-other") is None

    def test_unknown_model_returns_none(self):
        from app.services.embeddings import _query_prompt_for

        assert _query_prompt_for("totally-unknown/model-xyz") is None


class TestPassagePromptFor:
    """``_passage_prompt_for`` mirrors the query helper."""

    def test_listed_granite_311m_gets_prefix(self):
        from app.services.embeddings import (
            _GRANITE_PASSAGE_PROMPT,
            _passage_prompt_for,
        )

        assert (
            _passage_prompt_for("ibm-granite/granite-embedding-311m-multilingual-r2")
            == _GRANITE_PASSAGE_PROMPT
        )

    def test_bge_m3_returns_none(self):
        from app.services.embeddings import _passage_prompt_for

        assert _passage_prompt_for("BAAI/bge-m3") is None

    def test_unlisted_granite_returns_none(self):
        from app.services.embeddings import _passage_prompt_for

        assert _passage_prompt_for("ibm-granite/granite-embedding-2b-v2") is None


class TestEncodeManyPromptDelivery:
    """Verify the prefix is actually passed to the model in
    ``_encode_many`` (defence in depth — even if a future
    refactor changes the helper, the prefix must reach the
    model call).
    """

    def test_listed_model_receives_query_prefix(self):
        from unittest.mock import MagicMock

        from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

        client = LocalSentenceTransformerEmbeddingClient(
            model_name="ibm-granite/granite-embedding-311m-multilingual-r2",
            device="cpu",
        )
        # Mock the underlying model
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock()
        client._model = mock_model
        client._encode_many(["hello", "world"], role="query")
        # The encode call must include the prompt kwarg.
        _, kwargs = mock_model.encode.call_args
        assert "prompt" in kwargs
        assert kwargs["prompt"] == "query: "

    def test_unlisted_model_receives_no_prompt(self):
        from unittest.mock import MagicMock

        from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

        client = LocalSentenceTransformerEmbeddingClient(
            model_name="BAAI/bge-m3",  # symmetric
            device="cpu",
        )
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock()
        client._model = mock_model
        client._encode_many(["hello"], role="query")
        _, kwargs = mock_model.encode.call_args
        # No prompt kwarg for symmetric models.
        assert "prompt" not in kwargs or kwargs.get("prompt") is None

    def test_granite_prefix_match_with_unlisted_model_no_prompt(self):
        """The bug EMB-PROV-1 closes: a model whose name starts
        with the IBM Granite prefix but is NOT in the
        allow-list must NOT receive the prefix.
        """
        from unittest.mock import MagicMock

        from app.services.embeddings import LocalSentenceTransformerEmbeddingClient

        client = LocalSentenceTransformerEmbeddingClient(
            model_name="ibm-granite/granite-embedding-other",
            device="cpu",
        )
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock()
        client._model = mock_model
        client._encode_many(["hello"], role="query")
        _, kwargs = mock_model.encode.call_args
        # Critically: the prompt is NOT set.
        if "prompt" in kwargs:
            assert kwargs["prompt"] is None
        else:
            assert "prompt" not in kwargs