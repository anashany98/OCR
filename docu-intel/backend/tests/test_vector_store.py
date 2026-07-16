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


# PG-HNSW-01: ``_apply_hnsw_ef_search`` must issue a ``SET LOCAL`` using
# the configured value. The clamp protects against bad migrations of the
# env var; the SET LOCAL must use the clamped integer to match pgvector's
# documented contract (``1..1000`` range, default 40).


class _FakeSession:
    """Capture ``text(...)`` calls so we can assert the issued statement."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement) -> None:  # type: ignore[no-untyped-def]
        # ``text(...)`` instances stringify to their SQL; we only need the
        # command for the assertions below.
        self.executed.append(str(statement))


def test_apply_hnsw_ef_search_uses_configured_value(monkeypatch):
    from app.services import vector_store

    monkeypatch.setattr(settings, "search_hnsw_ef_search", 80)
    session = _FakeSession()
    vector_store._apply_hnsw_ef_search(session)  # type: ignore[arg-type]
    assert session.executed == ["SET LOCAL hnsw_ef_search = 80".replace(
        "hnsw_ef_search", "hnsw.ef_search"
    )]


def test_apply_hnsw_ef_search_clamps_low_values(monkeypatch, caplog):
    from app.services import vector_store

    monkeypatch.setattr(settings, "search_hnsw_ef_search", 5)
    session = _FakeSession()
    with caplog.at_level("WARNING"):
        vector_store._apply_hnsw_ef_search(session)  # type: ignore[arg-type]
    assert session.executed == ["SET LOCAL hnsw.ef_search = 20"]
    assert any("clampeado" in record.message for record in caplog.records)


def test_apply_hnsw_ef_search_clamps_high_values(monkeypatch, caplog):
    from app.services import vector_store

    monkeypatch.setattr(settings, "search_hnsw_ef_search", 999)
    session = _FakeSession()
    with caplog.at_level("WARNING"):
        vector_store._apply_hnsw_ef_search(session)  # type: ignore[arg-type]
    assert session.executed == ["SET LOCAL hnsw.ef_search = 200"]


def test_settings_reject_out_of_range_hnsw_ef_search(monkeypatch):
    """Pydantic constraint guards against impossible env var values."""
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("SEARCH_HNSW_EF_SEARCH", "5")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("SEARCH_HNSW_EF_SEARCH", "999")
    with pytest.raises(ValidationError):
        Settings()
