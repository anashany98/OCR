from __future__ import annotations

import pytest

from app.core.config import settings


def test_vector_literal_rejects_query_embedding_dimension_mismatch(monkeypatch):
    from app.services.vector_store import _vector_literal

    monkeypatch.setattr(settings, "embedding_dimensions", 3)

    with pytest.raises(ValueError, match="Query embedding dimension mismatch"):
        _vector_literal([0.1, 0.2])


def test_vector_literal_formats_expected_dimension(monkeypatch):
    from app.services.vector_store import _vector_literal

    monkeypatch.setattr(settings, "embedding_dimensions", 3)

    assert _vector_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"
