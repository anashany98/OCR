"""Tests for the ``reembed_document`` service function.

The function re-runs the embedding step for an existing document using
its stored page texts. It never raises on embedding failure — chunks
that still can't be embedded keep ``needs_reembedding=True`` so the
admin can try again.
"""
from __future__ import annotations

# Importing document_service at module level so it lives in sys.modules
# before the pipeline's ``_facade()`` looks it up. The facade is a
# thin wrapper that does ``_sys.modules["app.services.document_service"]``,
# so the module has to be importable for the patch to take.
from app.services import document_service  # noqa: F401  (imported for side effect)
from unittest.mock import patch

import pytest

from app.services.embeddings import EmbeddingProviderError


def _make_document_with_pages(db, *, page_text: str) -> int:
    """Create a Document + DocumentPage (no chunks yet). Returns the
    document id. ``reembed_document`` will chunk the page text and
    create the chunks itself, so the test can assert on the result."""
    from app.models import Document, DocumentPage

    document = Document(
        original_filename="reembed_test.pdf",
        stored_filename="aa/reembed_test.pdf",
        source_path="/data/input/reembed_test.pdf",
        file_hash="b" * 64,
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1024,
        document_type="invoice",
        status="processed",
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=page_text,
            ocr_confidence=0.9,
        )
    )
    db.commit()
    return document.id


def _n_chunks_for(db, document_id: int) -> int:
    """Count chunks the chunker would produce for the document's page
    text — used to build a matching mock embedding return value."""
    from app.services.document_embedding_pipeline import prepare_document_chunks

    from app.models import DocumentPage
    from sqlalchemy import select

    page_texts = [
        (p.page_number, p.text)
        for p in db.scalars(select(DocumentPage).where(DocumentPage.document_id == document_id)).all()
    ]
    return len(prepare_document_chunks(document_id, page_texts))


def test_reembed_document_populates_embeddings_on_success():
    """When the embedding provider works, all chunks get embeddings
    and ``needs_reembedding`` flips to False."""
    from app.database.base import Base
    from app.models import DocumentChunk
    from app.services.document_embedding_pipeline import reembed_document

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        document_id = _make_document_with_pages(
            db,
            page_text="Texto del documento de prueba para re-embedding. " * 10,
        )
        # Build a mock that returns the right number of vectors at the
        # model's expected dimension (1024 in the current schema).
        n = _n_chunks_for(db, document_id)
        dim = _embedding_dim_from_settings()
        fake_vectors = [[0.01 * (i + 1)] * dim for i in range(n)]

        with patch(
            "app.services.document_embedding_pipeline.embed_many",
            return_value=fake_vectors,
        ), patch(
            "app.services.document_embedding_pipeline.should_create_embeddings",
            return_value=True,
        ):
            result = reembed_document(db, document_id)

        assert result["document_id"] == document_id
        assert result["chunks_updated"] == n
        assert result["chunks_with_embedding"] == n
        assert result["chunks_needing_reembedding"] == 0

        db.expire_all()
        chunks = list(db.query(DocumentChunk).filter_by(document_id=document_id))
        assert len(chunks) == n
        for chunk in chunks:
            assert chunk.embedding is not None
            assert chunk.needs_reembedding is False


def _embedding_dim_from_settings() -> int:
    """The DocumentChunk.embedding column has a fixed dimension baked
    into the schema. Read it from the current settings so the test
    matches the real model."""
    from app.core.config import settings

    return int(settings.embedding_dimensions or 1024)


def test_reembed_document_preserves_unembedded_chunks_when_provider_fails():
    """If the provider still fails, chunks keep ``needs_reembedding=True``
    and ``embedding=None`` — no silent hash fallback."""
    from app.database.base import Base
    from app.models import DocumentChunk
    from app.services.document_embedding_pipeline import reembed_document

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        document_id = _make_document_with_pages(
            db,
            page_text="Texto del documento de prueba para re-embedding. " * 10,
        )
        n = _n_chunks_for(db, document_id)
        assert n > 0, "page text should produce at least one chunk"

        with patch(
            "app.services.document_embedding_pipeline.embed_many",
            side_effect=EmbeddingProviderError("model not loaded"),
        ), patch(
            "app.services.document_embedding_pipeline.should_create_embeddings",
            return_value=True,
        ):
            result = reembed_document(db, document_id)

        assert result["chunks_updated"] == n
        assert result["chunks_with_embedding"] == 0
        assert result["chunks_needing_reembedding"] == n

        db.expire_all()
        chunks = list(db.query(DocumentChunk).filter_by(document_id=document_id))
        for chunk in chunks:
            assert chunk.embedding is None
            assert chunk.needs_reembedding is True


def test_reembed_document_raises_on_missing_document():
    """Calling reembed on a non-existent document raises a clear error
    so the admin UI can show a 404 / not-found message."""
    from app.database.base import Base
    from app.services.document_embedding_pipeline import reembed_document

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        with pytest.raises(ValueError, match="not found"):
            reembed_document(db, 99999)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _memory_engine():
    """In-memory SQLite engine, shared in-memory + StaticPool so
    multiple sessions can see the same data."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _session_factory(engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
