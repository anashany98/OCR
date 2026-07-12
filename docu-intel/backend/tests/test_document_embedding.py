"""Tests for the whole-document embedding feature.

A single ``Document.embedding`` is computed from the concatenation of all
page texts and used by the document-level retrieval branch to improve
thematic recall (documents whose overall topic matches even when no
isolated chunk does). The feature reuses the existing embedding contract:
on provider failure it returns ``(None, "failed", True)`` — never a silent
hash fallback.
"""
from __future__ import annotations

from unittest.mock import patch

from app.services import document_service  # noqa: F401  (imported for side effect)
from app.services.embeddings import EmbeddingProviderError


def _embedding_dim_from_settings() -> int:
    from app.core.config import settings

    return int(settings.embedding_dimensions or 768)


def test_compute_document_embedding_returns_vector_on_success(monkeypatch):
    """Happy path: a whole-document embedding is produced and the
    provider label / fallback flag are returned alongside it."""
    from app.services.document_embedding_pipeline import compute_document_embedding
    from app.core.config import settings

    monkeypatch.setattr(settings, "embedding_provider", "local_openai_compatible")
    dim = _embedding_dim_from_settings()
    page_texts = [(1, "Primera página con contenido."), (2, "Segunda página con más texto.")]

    with patch(
        "app.services.document_embedding_pipeline.embed_many",
        return_value=[[0.1] * dim],
    ), patch(
        "app.services.document_embedding_pipeline.should_create_embeddings",
        return_value=True,
    ):
        embedding, provider, fallback = compute_document_embedding(page_texts)

    assert embedding is not None
    assert len(embedding) == dim
    assert fallback is False
    assert isinstance(provider, str)


def test_compute_document_embedding_truncates_to_token_budget():
    """The concatenated page text is truncated to
    ``document_embedding_max_tokens`` before embedding so we never exceed
    the model's context window."""
    from app.core.config import settings
    from app.services.document_embedding_pipeline import compute_document_embedding

    captured: dict[int, list[str]] = {}
    long_text = "palabra " * 60  # 60 words, well above the budget
    page_texts = [(1, long_text)]

    with patch(
        "app.services.document_embedding_pipeline.embed_many",
        side_effect=lambda texts: captured.setdefault(0, texts) or [[0.1] * _embedding_dim_from_settings()],
    ), patch(
        "app.services.document_embedding_pipeline.should_create_embeddings",
        return_value=True,
    ):
        with patch.object(settings, "document_embedding_max_tokens", 5):
            compute_document_embedding(page_texts)

    sent = captured[0][0]
    assert len(sent.split()) <= 5


def test_compute_document_embedding_fails_without_hash_fallback():
    """Provider failure yields ``(None, "failed", True)`` — the same
    contract as per-chunk embedding, no silent hash fallback."""
    from app.services.document_embedding_pipeline import compute_document_embedding

    page_texts = [(1, "Texto de prueba.")]

    with patch(
        "app.services.document_embedding_pipeline.embed_many",
        side_effect=EmbeddingProviderError("model not loaded"),
    ), patch(
        "app.services.document_embedding_pipeline.should_create_embeddings",
        return_value=True,
    ):
        result = compute_document_embedding(page_texts)

    assert result == (None, "failed", True)


def test_compute_document_embedding_skips_when_disabled():
    """When embeddings are disabled, no provider call happens and we get
    ``(None, None, False)``."""
    from app.services.document_embedding_pipeline import compute_document_embedding

    page_texts = [(1, "Texto de prueba.")]

    with patch(
        "app.services.document_embedding_pipeline.embed_many",
        return_value=[[0.1] * _embedding_dim_from_settings()],
    ), patch(
        "app.services.document_embedding_pipeline.should_create_embeddings",
        return_value=False,
    ):
        result = compute_document_embedding(page_texts)

    assert result == (None, None, False)


def test_apply_document_embedding_populates_document_embedding():
    """Ingestion wires the whole-document embedding onto ``Document``."""
    from app.database.base import Base
    from app.models import Document, DocumentPage
    from app.services.document_embedding_pipeline import apply_document_embedding

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        document = Document(
            original_filename="doc_level.pdf",
            stored_filename="aa/doc_level.pdf",
            source_path="/data/input/doc_level.pdf",
            file_hash="c" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=1024,
            document_type="factura",
            status="processed",
        )
        db.add(document)
        db.add(DocumentPage(document_id=document.id, page_number=1, text="Factura con importe."))
        db.commit()
        document_id = document.id

        dim = _embedding_dim_from_settings()
        with patch(
            "app.services.document_embedding_pipeline.embed_many",
            return_value=[[0.2] * dim],
        ), patch(
            "app.services.document_embedding_pipeline.should_create_embeddings",
            return_value=True,
        ):
            produced = apply_document_embedding(
                db, document_id, [(1, "Factura con importe.")]
            )

        assert produced is True
        db.expire_all()
        reloaded = db.get(Document, document_id)
        assert reloaded.embedding is not None
        assert reloaded.needs_reembedding is False


def test_apply_document_embedding_marks_needs_reembedding_on_failure():
    """Provider failure leaves the document without an embedding but flagged
    for the re-embed sweep (no silent fallback)."""
    from app.database.base import Base
    from app.models import Document, DocumentPage
    from app.services.document_embedding_pipeline import apply_document_embedding

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        document = Document(
            original_filename="doc_fail.pdf",
            stored_filename="aa/doc_fail.pdf",
            source_path="/data/input/doc_fail.pdf",
            file_hash="d" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=1024,
            document_type="factura",
            status="processed",
        )
        db.add(document)
        db.add(DocumentPage(document_id=document.id, page_number=1, text="Factura rota."))
        db.commit()
        document_id = document.id

        with patch(
            "app.services.document_embedding_pipeline.embed_many",
            side_effect=EmbeddingProviderError("model not loaded"),
        ), patch(
            "app.services.document_embedding_pipeline.should_create_embeddings",
            return_value=True,
        ):
            produced = apply_document_embedding(
                db, document_id, [(1, "Factura rota.")]
            )

        assert produced is False
        db.expire_all()
        reloaded = db.get(Document, document_id)
        assert reloaded.embedding is None
        assert reloaded.needs_reembedding is True


def test_search_documents_returns_doc_level_match_and_respects_filter():
    """The document-level retrieval branch returns ``VectorSearchMatch``
    rows with ``chunk_id=None`` and honours the ``document_type`` filter."""
    from app.database.base import Base
    from app.models import Document
    from app.services.vector_store import PgvectorStore

    dim = _embedding_dim_from_settings()
    query = [0.3] * dim
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        db.add(
            Document(
                original_filename="match.pdf",
                stored_filename="aa/match.pdf",
                file_hash="e" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=1024,
                document_type="factura",
                status="processed",
                embedding=list(query),
            )
        )
        db.add(
            Document(
                original_filename="other.pdf",
                stored_filename="aa/other.pdf",
                file_hash="f" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=1024,
                document_type="presupuesto",
                status="processed",
                embedding=list(query),
            )
        )
        db.commit()

        all_matches = PgvectorStore().search_documents(
            db, query_embedding=query, limit=10, filters={}
        )
        assert len(all_matches) == 2
        for m in all_matches:
            assert m.chunk_id is None
            assert m.page_number is None

        filtered = PgvectorStore().search_documents(
            db, query_embedding=query, limit=10, filters={"document_type": "factura"}
        )
        assert len(filtered) == 1
        assert filtered[0].document_type == "factura"


def test_search_documents_excludes_low_similarity_documents():
    """Documents whose whole-document embedding is nearly orthogonal to the
    query are dropped, keeping only relevant thematic matches."""
    from app.database.base import Base
    from app.models import Document
    from app.services.vector_store import PgvectorStore

    dim = _embedding_dim_from_settings()
    query = [0.3] * dim
    opposite = [-0.3] * dim
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        db.add(
            Document(
                original_filename="relevant.pdf",
                stored_filename="aa/relevant.pdf",
                file_hash="g" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=1024,
                document_type="factura",
                status="processed",
                embedding=list(query),
            )
        )
        db.add(
            Document(
                original_filename="irrelevant.pdf",
                stored_filename="aa/irrelevant.pdf",
                file_hash="h" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=1024,
                document_type="factura",
                status="processed",
                embedding=list(opposite),
            )
        )
        db.commit()

        matches = PgvectorStore().search_documents(
            db, query_embedding=query, limit=10, filters={}
        )
        assert len(matches) == 1
        assert matches[0].document_type == "factura"


def test_rrf_fuse_keeps_doc_and_chunk_matches():
    """Fusing chunk-level and document-level hits preserves both signals
    (they have different keys) and keeps each result's source_type."""
    from app.services.search_service import _rrf_fuse
    from app.services.search_service import SearchResult

    chunk = SearchResult(
        document_id=1,
        original_filename="x.pdf",
        document_type="factura",
        status="processed",
        page_number=1,
        block_id=None,
        chunk_id=10,
        score=0.9,
        excerpt="",
        ocr_confidence=None,
        source_type="semantic_chunk",
    )
    doc = SearchResult(
        document_id=1,
        original_filename="x.pdf",
        document_type="factura",
        status="processed",
        page_number=None,
        block_id=None,
        chunk_id=None,
        score=0.8,
        excerpt="",
        ocr_confidence=None,
        source_type="semantic_document",
    )

    fused = _rrf_fuse([[chunk], [doc]], limit=10)

    assert len(fused) == 2
    source_types = {item.source_type for item in fused}
    assert "semantic_chunk" in source_types
    assert "semantic_document" in source_types


def _memory_engine():
    """In-memory SQLite engine, shared in-memory + StaticPool so multiple
    sessions can see the same data."""
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
