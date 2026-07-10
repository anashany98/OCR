"""
Unit tests for EMB-DIM-1 (Sprint 2).

The default EMBEDDING_DIMENSIONS is 768 (matching the pgvector column).
These tests verify:

1. ``EMBEDDING_DIMENSIONS`` defaults to ``768`` when the setting is 0.
2. ``EMBEDDING_DIMENSIONS`` honours the operator's explicit setting.
3. ``coerce_embedding_dimensions`` raises a clear error when
   the dimension does not match (defence in depth).
"""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


class TestEmbeddingDimensionsDefault:
    """``EMBEDDING_DIMENSIONS`` must default to 768 (the pgvector column)."""

    def test_default_is_768(self):
        with patch("app.core.config.settings.embedding_dimensions", 0):
            import importlib
            from app.services import embeddings
            importlib.reload(embeddings)
            try:
                assert embeddings.EMBEDDING_DIMENSIONS == 768
            finally:
                importlib.reload(embeddings)

    def test_falsy_setting_uses_768(self):
        with patch("app.core.config.settings.embedding_dimensions", 0):
            import importlib
            from app.services import embeddings
            importlib.reload(embeddings)
            try:
                assert embeddings.EMBEDDING_DIMENSIONS == 768
            finally:
                importlib.reload(embeddings)

    def test_explicit_setting_is_honoured(self):
        with patch("app.core.config.settings.embedding_dimensions", 1024):
            import importlib
            from app.services import embeddings
            importlib.reload(embeddings)
            try:
                assert embeddings.EMBEDDING_DIMENSIONS == 1024
            finally:
                importlib.reload(embeddings)


class TestCoerceEmbeddingDimensions:
    """Defence in depth: the provider might return a wrong dim."""

    def test_raises_on_mismatch_when_coercion_disabled(self):
        import pytest
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
