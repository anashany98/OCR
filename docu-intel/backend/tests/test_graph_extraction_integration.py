"""Regression tests for the Graph RAG integration (2026-07-16).

Three regressions this file pins:

1. ``_upsert_relation`` returns the new id via ``result.scalar()``
   instead of ``result.scalarone_or_none()``. The chunked-iterator
   result returned by ``db.execute(insert_stmt).returning(...)`` does
   not implement ``scalarone_or_none`` and the call raises
   ``AttributeError`` on first use. The previous behaviour silently
   dropped every relation into ``graph_extraction_errors`` even
   though the insert itself succeeded.

2. ``run_extraction`` accepts ``tenant_id=None`` for deployments
   that have no ``hotel_chains`` rows yet. Migration 0065 made the
   column nullable to support this.

3. ``_run_graph_extraction_after_commit`` does not raise on
   transient errors; it logs and continues.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fix A: _upsert_relation uses result.scalar() (not scalarone_or_none)
# ---------------------------------------------------------------------------


def test_upsert_relation_uses_scalar_not_scalarone_or_none(monkeypatch):
    """The chunked-iterator result has no ``scalarone_or_none``."""
    from app.services import graph_extraction

    # ChunkedIteratorResult exposes .scalar() but not .scalarone_or_none().
    class FakeChunkedResult:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

        def scalarone_or_none(self):  # pragma: no cover - asserts failure
            raise AttributeError("ChunkedIteratorResult has no attribute 'scalarone_or_none'")

    db = MagicMock()
    db.execute.return_value = FakeChunkedResult(42)
    db.scalar.return_value = 42  # for the duplicate-lookup branch

    proposal = SimpleNamespace(
        source_entity_type="document",
        source_entity_value="1",
        source_normalized_value=None,
        target_entity_type="document",
        target_entity_value="2",
        target_normalized_value=None,
        relation_type="shared_reference",
        confidence=0.9,
    )

    result = graph_extraction._upsert_relation(db, source_id=1, target_id=2, proposal=proposal)
    assert result == 42
    # Ensure the call used .scalar(), not .scalarone_or_none().
    db.execute.assert_called_once()


def test_upsert_relation_handles_duplicate(monkeypatch):
    """When the unique key collides, the existing id is returned."""
    from app.services import graph_extraction

    class FakeChunkedResult:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    # First call (the INSERT) returns None (the row was already there).
    # Second call (the duplicate lookup) returns the existing id.
    db = MagicMock()
    db.execute.return_value = FakeChunkedResult(None)
    db.scalar.return_value = 7

    proposal = SimpleNamespace(
        source_entity_type="document",
        source_entity_value="1",
        source_normalized_value=None,
        target_entity_type="document",
        target_entity_value="2",
        target_normalized_value=None,
        relation_type="shared_reference",
        confidence=0.9,
    )

    result = graph_extraction._upsert_relation(db, source_id=1, target_id=2, proposal=proposal)
    assert result == 7


# ---------------------------------------------------------------------------
# Fix B: run_extraction accepts tenant_id=None
# ---------------------------------------------------------------------------


def test_run_extraction_signature_accepts_none_tenant():
    """The signature must accept ``tenant_id: int | None``."""
    import inspect

    sig = inspect.signature(__import__("app.services.graph_extraction", fromlist=["run_extraction"]).run_extraction)
    tenant_id_param = sig.parameters["tenant_id"]
    # The annotation is ``int | None`` so the string is "int | None" or
    # "Optional[int]". We only assert that the parameter is not annotated
    # as int-only.
    assert tenant_id_param.annotation != int, (
        f"tenant_id must accept None, got annotation {tenant_id_param.annotation!r}"
    )


# ---------------------------------------------------------------------------
# Fix C: _run_graph_extraction_after_commit is best-effort
# ---------------------------------------------------------------------------


def test_graph_extraction_after_commit_swallows_internal_errors(monkeypatch):
    """The function's internal try/except must log + return, not raise."""
    import app.services.document_processing_core as dpc

    class _FakeSession:
        def get(self, _model, _id):
            return SimpleNamespace(id=_id, budget_scope_id=None)

        def scalar(self, _stmt):
            return None

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    # The function imports ``SessionLocal`` locally from
    # ``app.database.session``; patch the symbol at its source.
    monkeypatch.setattr("app.database.session.SessionLocal", lambda: _FakeSession())

    def _raise(*args, **kwargs):
        raise RuntimeError("graph extraction failed for the test")

    # ``run_extraction`` is imported locally as well; patch at its source.
    monkeypatch.setattr("app.services.graph_extraction.run_extraction", _raise)

    # Must NOT raise.
    dpc._run_graph_extraction_after_commit(99, 7)
