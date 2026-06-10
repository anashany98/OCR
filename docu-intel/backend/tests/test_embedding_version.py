"""Tests for E4 — versioned embedding model.

The versioned-embedding feature is mostly a schema change (a new
column on ``DocumentChunk``) and a helper function that counts
chunks whose ``embedding_model_version`` differs from the current
``settings.embedding_model``. The tests below verify the logic
without requiring a real database by mocking the SQLAlchemy query.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.embeddings import chunks_needing_model_migration


def test_chunks_needing_model_migration_returns_zero_when_all_match(monkeypatch):
    from app.services import embeddings

    monkeypatch.setattr(embeddings.settings, "embedding_model", "bge-m3")
    db = MagicMock()
    db.scalar.return_value = 0
    assert chunks_needing_model_migration(db) == 0


def test_chunks_needing_model_migration_counts_old_versions(monkeypatch):
    from app.services import embeddings

    monkeypatch.setattr(embeddings.settings, "embedding_model", "bge-m3-v2")
    db = MagicMock()
    db.scalar.return_value = 5
    assert chunks_needing_model_migration(db) == 5


def test_chunks_needing_model_migration_returns_zero_when_model_empty(monkeypatch):
    from app.services import embeddings

    monkeypatch.setattr(embeddings.settings, "embedding_model", "")
    db = MagicMock()
    assert chunks_needing_model_migration(db) == 0


def test_chunks_needing_model_migration_returns_zero_when_none(monkeypatch):
    from app.services import embeddings

    monkeypatch.setattr(embeddings.settings, "embedding_model", "bge-m3")
    db = MagicMock()
    db.scalar.return_value = None
    assert chunks_needing_model_migration(db) == 0
