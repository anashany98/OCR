"""
Unit tests for EMB-DIM-1 (Sprint 2).

The previous implementation of ``EMBEDDING_DIMENSIONS`` had a
silent fallback to ``768`` when the operator's ``.env`` was missing
``EMBEDDING_DIMENSIONS`` (or set to an empty value). The pgvector
column is hard-coded to ``1024``, so the fallback was a silent
dimension mismatch. ``coerce_embedding_dimensions`` would raise
later with a confusing error, but by then the embedding write
had already been lost.

These tests verify the new behaviour:

1. ``EMBEDDING_DIMENSIONS`` defaults to ``1024`` (matching the
   pgvector column) when ``settings.embedding_dimensions`` is
   empty.
2. ``EMBEDDING_DIMENSIONS`` honours the operator's explicit
   setting.
3. ``coerce_embedding_dimensions`` raises a clear error when
   the dimension does not match (defence in depth — the
   upstream provider might return 768 even if the column is
   1024).
"""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


class TestEmbeddingDimensionsDefault:
    """``EMBEDDING_DIMENSIONS`` must default to 1024 (the pgvector
    column dimension), NOT 768 (which would silently mismatch).
    """

    def test_default_is_1024(self):
        # Re-import the module with a cleared setting.
        with patch("app.core.config.settings.embedding_dimensions", 0):
            # Reload the module so the constant is recomputed.
            import importlib

            from app.services import embeddings
            importlib.reload(embeddings)
            try:
                assert embeddings.EMBEDDING_DIMENSIONS == 1024
            finally:
                importlib.reload(embeddings)  # restore

    def test_falsy_setting_uses_1024_not_768(self):
        """An empty string (``EMBEDDING_DIMENSIONS=``) is the
        historical case that triggered the 768 fallback.
        """
        with patch("app.core.config.settings.embedding_dimensions", 0):
            import importlib

            from app.services import embeddings
            importlib.reload(embeddings)
            try:
                # The bug: the previous code returned 768 here.
                # The fix: it now returns 1024.
                assert embeddings.EMBEDDING_DIMENSIONS != 768
                assert embeddings.EMBEDDING_DIMENSIONS == 1024
            finally:
                importlib.reload(embeddings)  # restore

    def test_explicit_setting_is_honoured(self):
        """When the operator sets a value, it wins."""
        with patch("app.core.config.settings.embedding_dimensions", 768):
            import importlib

            from app.services import embeddings
            importlib.reload(embeddings)
            try:
                assert embeddings.EMBEDDING_DIMENSIONS == 768
            finally:
                importlib.reload(embeddings)  # restore


class TestCoerceEmbeddingDimensions:
    """Defence in depth: the provider might return a wrong dim
    even after we fix the fallback. ``coerce_embedding_dimensions``
    raises a clear error.
    """

    def test_raises_on_mismatch_when_coercion_disabled(self):
        from app.core.config import settings
        from app.services.embeddings import (
            EmbeddingProviderError,
            coerce_embedding_dimensions,
        )

        original = settings.embedding_allow_dimension_coercion
        try:
            settings.embedding_allow_dimension_coercion = False
            with pytest.raises(EmbeddingProviderError) as excinfo:
                coerce_embedding_dimensions([0.0] * 768, 1024)
            assert "dimension mismatch" in str(excinfo.value).lower()
            assert "768" in str(excinfo.value)
            assert "1024" in str(excinfo.value)
        finally:
            settings.embedding_allow_dimension_coercion = original

    def test_pads_when_coercion_enabled(self):
        """Legacy fallback: when the operator opts in to coercion,
        the vector is padded with zeros to the expected dim.
        """
        from app.core.config import settings
        from app.services.embeddings import coerce_embedding_dimensions

        original = settings.embedding_allow_dimension_coercion
        try:
            settings.embedding_allow_dimension_coercion = True
            out = coerce_embedding_dimensions([0.1] * 768, 1024)
            assert len(out) == 1024
            assert out[:768] == [0.1] * 768
            assert out[768:] == [0.0] * 256
        finally:
            settings.embedding_allow_dimension_coercion = original

    def test_no_passthrough_when_dims_match(self):
        from app.core.config import settings
        from app.services.embeddings import coerce_embedding_dimensions

        original = settings.embedding_allow_dimension_coercion
        try:
            settings.embedding_allow_dimension_coercion = False
            vec = [0.5] * 1024
            out = coerce_embedding_dimensions(vec, 1024)
            assert out == vec
        finally:
            settings.embedding_allow_dimension_coercion = original


def test_document_chunk_vector_dimension_matches_settings():
    """The ORM pgvector dimension must match the configured model size."""
    from app.core.config import settings
    from app.models import DocumentChunk

    column_dim = getattr(DocumentChunk.__table__.c.embedding.type, "dim", None)

    assert column_dim == int(settings.embedding_dimensions)


# Need pytest for raises
import pytest
