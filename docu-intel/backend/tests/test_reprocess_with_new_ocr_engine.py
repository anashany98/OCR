"""Tests for the periodic OCR engine-version sweeper task (Mejora 3).

This task runs on Celery Beat (queue ``maintenance``) and re-runs the
processing pipeline for every document that has at least one page
processed with a stale ``ocr_engine_version`` (i.e. an older PaddleOCR /
Tesseract build than the one configured in
``settings.current_ocr_engine_version``). It must:

* find documents with at least one page stamped with a different
  (older) engine version, or with no version at all (NULL);
* skip documents that are already in a transient state
  (``pending`` / ``processing`` / ``duplicate``);
* skip soft-deleted documents;
* cap the number of re-OCR jobs enqueued per tick to
  ``reocr_versioned_per_tick``;
* be a no-op when the master switch
  ``ocr_reprocess_on_version_drift`` is off;
* never crash the whole tick on a single document failure.

We call the pure ``run_reprocess_with_new_ocr_engine`` function (not
the Celery task) with an in-memory SQLite engine so the test does not
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
    deleted: bool = False,
    page_versions: list[str | None] | None = None,
) -> int:
    """Create a document with the given number of pages, each stamped
    with the requested ``ocr_engine_version`` (or NULL when the entry
    in the list is None)."""
    from app.models import Document, DocumentPage

    document = Document(
        original_filename=f"doc_{document_id_seed}.pdf",
        stored_filename=f"aa/doc_{document_id_seed}.pdf",
        source_path=f"/data/input/doc_{document_id_seed}.pdf",
        file_hash=("b" * 63 + str(document_id_seed % 10)),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1024,
        document_type="invoice",
        status=status,
        confidence=0.85,
        needs_reembedding=False,
        deleted_at=None if not deleted else _now(),
    )
    db.add(document)
    db.flush()
    for idx, version in enumerate(page_versions or [], start=1):
        db.add(
            DocumentPage(
                document_id=document.id,
                page_number=idx,
                text=f"Pagina {idx} del documento {document_id_seed}.",
                ocr_confidence=0.85,
                ocr_engine_version=version,
            )
        )
    db.commit()
    return document.id


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def test_versioned_reocr_picks_up_documents_with_stale_engine():
    """A document with at least one page stamped with an older engine
    version is enqueued for full reprocess via the heavy queue helper."""
    from unittest.mock import patch

    from app.core.config import settings
    from app.database.base import Base
    from app.workers.embedding_tasks import run_reprocess_with_new_ocr_engine

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)

    current = settings.current_ocr_engine_version

    with Session() as db:
        stale_id = _make_document(
            db,
            document_id_seed=1,
            page_versions=["paddleocr-v2", "paddleocr-v2"],
        )
        fresh_id = _make_document(
            db,
            document_id_seed=2,
            page_versions=[current, current],
        )
        null_id = _make_document(
            db,
            document_id_seed=3,
            page_versions=[None, None],
        )

        original_switch = settings.ocr_reprocess_on_version_drift
        original_cap = settings.reocr_versioned_per_tick
        settings.ocr_reprocess_on_version_drift = True
        # Raise the per-tick cap so all stale documents can be queued
        # in a single tick — this test is verifying the candidate
        # selection logic, not the cap.
        settings.reocr_versioned_per_tick = 50
        try:
            with patch(
                "app.workers.embedding_tasks._enqueue_versioned_reocr",
                return_value=None,
            ) as enqueue_mock:
                result = run_reprocess_with_new_ocr_engine(db)
        finally:
            settings.ocr_reprocess_on_version_drift = original_switch
            settings.reocr_versioned_per_tick = original_cap

    assert result["inspected"] == 2
    assert result["queued"] == 2
    assert result["errors"] == 0
    assert result["current_version"] == current
    enqueued_ids = {call.args[1].id for call in enqueue_mock.call_args_list}
    assert stale_id in enqueued_ids
    assert null_id in enqueued_ids
    assert fresh_id not in enqueued_ids


def test_versioned_reocr_skips_when_disabled():
    """When ``ocr_reprocess_on_version_drift`` is False, the sweep is
    a no-op and no candidate selection is performed."""
    from unittest.mock import patch

    from app.core.config import settings
    from app.workers.embedding_tasks import run_reprocess_with_new_ocr_engine

    original_switch = settings.ocr_reprocess_on_version_drift
    settings.ocr_reprocess_on_version_drift = False
    try:
        with patch(
            "app.workers.embedding_tasks._select_stale_engine_documents",
            return_value=[],
        ) as select_mock, patch(
            "app.workers.embedding_tasks._enqueue_versioned_reocr",
            return_value=None,
        ) as enqueue_mock:
            result = run_reprocess_with_new_ocr_engine(None)  # type: ignore[arg-type]
    finally:
        settings.ocr_reprocess_on_version_drift = original_switch

    assert result["skipped"] == "disabled"
    assert result["inspected"] == 0
    assert result["queued"] == 0
    select_mock.assert_not_called()
    enqueue_mock.assert_not_called()


def test_versioned_reocr_caps_per_tick():
    """Even with several stale documents, the per-tick cap
    (``reocr_versioned_per_tick``) limits how many get enqueued."""
    from unittest.mock import patch

    from app.core.config import settings
    from app.database.base import Base
    from app.workers.embedding_tasks import run_reprocess_with_new_ocr_engine

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)

    with Session() as db:
        for seed in range(10, 15):
            _make_document(
                db,
                document_id_seed=seed,
                page_versions=["paddleocr-v1"],
            )

    original_switch = settings.ocr_reprocess_on_version_drift
    original_cap = settings.reocr_versioned_per_tick
    settings.ocr_reprocess_on_version_drift = True
    settings.reocr_versioned_per_tick = 1
    try:
        with patch(
            "app.workers.embedding_tasks._enqueue_versioned_reocr",
            return_value=None,
        ) as enqueue_mock:
            result = run_reprocess_with_new_ocr_engine(Session())
    finally:
        settings.ocr_reprocess_on_version_drift = original_switch
        settings.reocr_versioned_per_tick = original_cap

    # The cap doubles as the SELECT limit so only one document is even
    # inspected this tick; the rest are picked up on subsequent ticks.
    assert result["inspected"] == 1
    assert result["queued"] == 1
    enqueue_mock.assert_called_once()


def test_versioned_reocr_ignores_pending_and_duplicate_documents():
    """The sweeper must not touch documents that are already in a
    transient state or that are soft-deleted, otherwise it would race
    with the original processing job."""
    from app.core.config import settings
    from app.database.base import Base
    from app.workers.embedding_tasks import _select_stale_engine_documents

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)

    current = settings.current_ocr_engine_version

    with Session() as db:
        _make_document(db, document_id_seed=20, status="pending", page_versions=["paddleocr-v1"])
        _make_document(db, document_id_seed=21, status="processing", page_versions=["paddleocr-v1"])
        _make_document(db, document_id_seed=22, status="duplicate", page_versions=["paddleocr-v1"])
        _make_document(db, document_id_seed=23, deleted=True, page_versions=["paddleocr-v1"])
        ok_id = _make_document(
            db,
            document_id_seed=24,
            status="processed",
            page_versions=["paddleocr-v1"],
        )

        ids = _select_stale_engine_documents(db, current_version=current, limit=50)

    assert ids == [ok_id]


def test_versioned_reocr_continues_after_individual_failure():
    """A failure enqueueing one document must not stop the rest of the
    tick — the sweeper logs the error and moves on to the next stale
    document."""
    from unittest.mock import MagicMock, patch

    from app.core.config import settings
    from app.database.base import Base
    from app.workers.embedding_tasks import run_reprocess_with_new_ocr_engine

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)

    current = settings.current_ocr_engine_version

    with Session() as db:
        ids = [
            _make_document(db, document_id_seed=30, page_versions=["paddleocr-v1"]),
            _make_document(db, document_id_seed=31, page_versions=["paddleocr-v1"]),
        ]
        # Force ``db.get`` to return a real Document for each id so the
        # inner loop has something to operate on.
        original_get = db.get

        def _patched_get(model, pk):  # type: ignore[no-untyped-def]
            if model.__name__ == "Document" and pk in ids:
                return original_get(model, pk)
            return original_get(model, pk)

        with patch.object(db, "get", side_effect=_patched_get):
            with patch(
                "app.workers.embedding_tasks._enqueue_versioned_reocr",
                side_effect=[RuntimeError("boom"), None],
            ) as enqueue_mock:
                original_switch = settings.ocr_reprocess_on_version_drift
                original_cap = settings.reocr_versioned_per_tick
                settings.ocr_reprocess_on_version_drift = True
                settings.reocr_versioned_per_tick = 50
                try:
                    result = run_reprocess_with_new_ocr_engine(db)
                finally:
                    settings.ocr_reprocess_on_version_drift = original_switch
                    settings.reocr_versioned_per_tick = original_cap

    assert result["inspected"] == 2
    assert result["queued"] == 1
    assert result["errors"] == 1
    assert enqueue_mock.call_count == 2


def test_settings_expose_ocr_engine_version_switches():
    """The default settings must expose the engine-version knobs the
    task relies on, otherwise the sweep cannot be configured from the
    environment."""
    from app.core.config import settings

    assert isinstance(settings.current_ocr_engine_version, str)
    assert settings.current_ocr_engine_version  # non-empty by default
    assert isinstance(settings.reocr_versioned_per_tick, int)
    assert settings.reocr_versioned_per_tick >= 1
    # Master switch defaults to off so deployments that have not
    # migrated pick up no extra work.
    assert settings.ocr_reprocess_on_version_drift is False
