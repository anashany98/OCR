"""F2-03: Tests that lock query and passage embedding roles.

Granite 311M uses asymmetric embeddings: queries get "query: " prefix
and passages get "passage: " prefix. These tests verify the roles are
applied correctly and never mixed.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestEmbeddingRoles:
    """Verify query/passage role separation."""

    def test_granite_model_is_in_asymmetric_set(self):
        """Granite R2 must be registered as asymmetric."""
        from app.services.embeddings import _ASYMMETRIC_MODELS
        assert "ibm-granite/granite-embedding-311m-multilingual-r2" in _ASYMMETRIC_MODELS

    def test_query_prompt_for_granite(self):
        """Granite gets the 'query: ' prompt."""
        from app.services.embeddings import _query_prompt_for
        prompt = _query_prompt_for("ibm-granite/granite-embedding-311m-multilingual-r2")
        assert prompt == "query: "

    def test_passage_prompt_for_granite(self):
        """Granite gets the 'passage: ' prompt."""
        from app.services.embeddings import _passage_prompt_for
        prompt = _passage_prompt_for("ibm-granite/granite-embedding-311m-multilingual-r2")
        assert prompt == "passage: "

    def test_symmetric_model_no_prompt(self):
        """Symmetric models (like bge-m3) should not get role prompts."""
        from app.services.embeddings import _query_prompt_for, _passage_prompt_for
        assert _query_prompt_for("BAAI/bge-m3") is None
        assert _passage_prompt_for("BAAI/bge-m3") is None

    def test_embed_query_uses_query_role(self):
        """embed_query calls encode with query prompt prefix."""
        import numpy as np
        from app.services.embeddings import LocalSentenceTransformerEmbeddingClient
        client = LocalSentenceTransformerEmbeddingClient.__new__(LocalSentenceTransformerEmbeddingClient)
        client.model_name = "ibm-granite/granite-embedding-311m-multilingual-r2"
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1] * 768])
        client._model = mock_model
        client.embed_query("test query")
        kwargs = mock_model.encode.call_args[1]
        assert kwargs.get("prompt") == "query: "

    def test_embed_many_passage_role(self):
        """embed_passages calls encode with passage prompt prefix."""
        import numpy as np
        from app.services.embeddings import LocalSentenceTransformerEmbeddingClient
        client = LocalSentenceTransformerEmbeddingClient.__new__(LocalSentenceTransformerEmbeddingClient)
        client.model_name = "ibm-granite/granite-embedding-311m-multilingual-r2"
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1] * 768, [0.2] * 768])
        client._model = mock_model
        client.embed_passages(["text1", "text2"])
        kwargs = mock_model.encode.call_args[1]
        assert kwargs.get("prompt") == "passage: "

    def test_cosine_similarity_rejects_mismatch(self):
        """F2-02: cosine_similarity must fail on dimension mismatch."""
        from app.services.embeddings import cosine_similarity, EmbeddingProviderError
        with pytest.raises(EmbeddingProviderError, match="dimension mismatch"):
            cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_cosine_similarity_works_on_match(self):
        """cosine_similarity returns correct value for matching dimensions."""
        from app.services.embeddings import cosine_similarity
        result = cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(result) < 1e-10  # orthogonal vectors

    def test_cosine_similarity_identical_vectors(self):
        """Identical vectors should have similarity ~1.0."""
        from app.services.embeddings import cosine_similarity
        result = cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert abs(result - 1.0) < 1e-10
