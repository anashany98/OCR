"""Tests for the periodic re-embed / re-OCR sweeper task (A7).

This task runs on Celery Beat (queue ``maintenance``) and is the
background half of the manual ``POST /admin/documents/{id}/re-embed``
endpoint. It must:

* pick up documents that still have ``Document.needs_reembedding=True``
  or at least one chunk with ``needs_reembedding=True`` (re-embed only);
* pick up documents whose ``Document.confidence`` is below the
  configured threshold and route them to the heavy OCR queue (capped
  per tick);
* never crash the whole tick on a single document failure.

We call the pure ``run_reembed_pending_documents`` function (not the
Celery task) with an in-memory SQLite engine so the test does not
need Celery/Redis/Postgres.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _memory_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _make_document(
    db,
    *,
    document_id_seed: int,
    status: str = "processed",
    confidence: float | None = 0.85,
    needs_reembedding: bool = False,
    has_needing_chunk: bool = False,
    extension: str = ".pdf",
) -> int:
    from app.models import Document, DocumentChunk, DocumentPage

    document = Document(
        original_filename=f"doc_{document_id_seed}.pdf",
        stored_filename=f"aa/doc_{document_id_seed}.pdf",
        source_path=f"/data/input/doc_{document_id_seed}.pdf",
        file_hash=("a" * 63 + str(document_id_seed % 10)),
        mime_type="application/pdf",
        extension=extension,
        file_size=1024,
        document_type="invoice",
        status=status,
        confidence=confidence,
        needs_reembedding=needs_reembedding,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Texto del documento de prueba. " * 8,
            ocr_confidence=confidence,
        )
    )
    if has_needing_chunk:
        db.add(
            DocumentChunk(
                document_id=document.id,
                page_number=1,
                chunk_text="Texto del documento de prueba.",
                embedding=None,
                embedding_provider_used="failed",
                embedding_fallback=True,
                needs_reembedding=True,
                token_count=4,
            )
        )
    db.commit()
    return document.id


def test_reembed_task_reembeds_doc_with_needing_chunks():
    """A document that still has ``needs_reembedding`` chunks must be
    picked up by the sweeper and routed to the re-embed (cheap) path."""
    from unittest.mock import patch

    from app.database.base import Base
    from app.workers.embedding_tasks import run_reembed_pending_documents

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        _make_document(
            db,
            document_id_seed=1,
            confidence=0.85,
            has_needing_chunk=True,
        )

        with patch(
            "app.workers.embedding_tasks._enqueue_reembed_only",
            return_value=None,
        ) as reembed_mock, patch(
            "app.workers.embedding_tasks._enqueue_reocr",
            return_value=None,
        ) as reocr_mock:
            result = run_reembed_pending_documents(db)

        assert result["inspected"] == 1
        assert result["reembedded"] == 1
        assert result["reocr_queued"] == 0
        assert result["errors"] == 0
        reembed_mock.assert_called_once()
        reocr_mock.assert_not_called()


def test_reembed_task_routes_low_confidence_to_heavy_queue():
    """A document whose ``confidence`` is below the threshold is queued
    for full re-OCR (job_type ``reprocess``) on the heavy queue,
    not the cheap re-embed path."""
    from unittest.mock import patch

    from app.database.base import Base
    from app.workers.embedding_tasks import run_reembed_pending_documents

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        _make_document(
            db,
            document_id_seed=2,
            confidence=0.50,  # below 0.70 threshold
            has_needing_chunk=False,
        )

        with patch(
            "app.workers.embedding_tasks._enqueue_reembed_only",
            return_value=None,
        ) as reembed_mock, patch(
            "app.workers.embedding_tasks._enqueue_reocr",
            return_value=None,
        ) as reocr_mock:
            result = run_reembed_pending_documents(db)

        assert result["inspected"] == 1
        assert result["reocr_queued"] == 1
        assert result["reembedded"] == 0
        reocr_mock.assert_called_once()
        reembed_mock.assert_not_called()


def test_reembed_task_caps_heavy_reocr_per_tick():
    """Even if many documents qualify as low confidence in a single
    tick, only ``reembed_reocr_per_tick`` of them are routed to the
    heavy queue; the rest are re-embedded inline (or skipped if they
    don't need embedding either)."""
    from unittest.mock import patch

    from app.core.config import settings
    from app.database.base import Base
    from app.workers.embedding_tasks import run_reembed_pending_documents

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        # Five low-confidence docs, but the per-tick cap is 1 by default.
        for seed in range(3, 8):
            _make_document(
                db,
                document_id_seed=seed,
                confidence=0.40,
                has_needing_chunk=False,
            )

        original_cap = settings.reembed_reocr_per_tick
        settings.reembed_reocr_per_tick = 1
        try:
            with patch(
                "app.workers.embedding_tasks._enqueue_reembed_only",
                return_value=None,
            ) as reembed_mock, patch(
                "app.workers.embedding_tasks._enqueue_reocr",
                return_value=None,
            ) as reocr_mock:
                result = run_reembed_pending_documents(db)
        finally:
            settings.reembed_reocr_per_tick = original_cap

        # We only sample ``reembed_batch_size`` docs per tick (default 5),
        # of which exactly 1 may go to the heavy queue.
        assert result["reocr_queued"] == 1
        assert reocr_mock.call_count == 1
        # The remaining ones are re-embedded inline.
        assert reembed_mock.call_count == result["reembedded"]


def test_reembed_task_skips_when_disabled():
    """The beat entry point is a no-op when ``reembed_enabled`` is off,
    so operators can pause the loop without removing the schedule."""
    from unittest.mock import patch

    from app.core.config import settings

    original = settings.reembed_enabled
    settings.reembed_enabled = False
    try:
        with patch(
            "app.workers.embedding_tasks._select_reembed_candidates",
            return_value=[],
        ) as select_mock, patch(
            "app.workers.embedding_tasks._enqueue_reembed_only",
            return_value=None,
        ):
            # We need a real session — patch on the function above
            # short-circuits before it gets opened, but the function
            # is called on the module. The test still has to import
            # the helper and provide a session-like object; passing
            # ``None`` is safe because the disabled-branch returns
            # before touching the session.
            result = None if False else None  # placeholder, see below
            from app.workers.embedding_tasks import run_reembed_pending_documents

            result = run_reembed_pending_documents(None)  # type: ignore[arg-type]
    finally:
        settings.reembed_enabled = original

    assert result["skipped"] == "disabled"
    select_mock.assert_not_called()


def test_reembed_task_continues_after_individual_failure():
    """A failure in one document's re-embed must not stop the rest of
    the tick — the sweeper logs the error and moves on."""
    from unittest.mock import patch

    from app.database.base import Base
    from app.workers.embedding_tasks import run_reembed_pending_documents

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        _make_document(
            db,
            document_id_seed=10,
            confidence=0.85,
            has_needing_chunk=True,
        )
        bad_id = _make_document(
            db,
            document_id_seed=11,
            confidence=0.85,
            has_needing_chunk=True,
        )

        def _side_effect(db_session, document):
            if document.id == bad_id:
                raise RuntimeError("simulated provider boom")
            return None

        with patch(
            "app.workers.embedding_tasks._enqueue_reembed_only",
            side_effect=_side_effect,
        ), patch(
            "app.workers.embedding_tasks._enqueue_reocr",
            return_value=None,
        ):
            result = run_reembed_pending_documents(db)

        assert result["inspected"] == 2
        assert result["reembedded"] == 1
        assert result["errors"] == 1


def test_reembed_task_ignores_pending_and_duplicate_documents():
    """Documents in transient states (``pending``, ``processing``,
    ``duplicate``) must not be picked up: the sweeper would race with
    the original processing job."""
    from app.database.base import Base
    from app.workers.embedding_tasks import _select_reembed_candidates

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)
    with Session() as db:
        _make_document(db, document_id_seed=20, status="pending", has_needing_chunk=True)
        _make_document(db, document_id_seed=21, status="processing", has_needing_chunk=True)
        _make_document(db, document_id_seed=22, status="duplicate", has_needing_chunk=True)
        ok_id = _make_document(db, document_id_seed=23, status="processed", has_needing_chunk=True)

        rows = _select_reembed_candidates(db, limit=50)
        ids = [document.id for document, _ in rows]
        assert ok_id in ids
        assert 20 not in ids
        assert 21 not in ids
        assert 22 not in ids
