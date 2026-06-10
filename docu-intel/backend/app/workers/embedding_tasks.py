from __future__ import annotations

import logging

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.models import Document, DocumentChunk, DocumentPage, ExtractionJob
from app.services.cache import cache_service
from app.workers.celery_app import celery_app
from app.workers.routing import queue_for_document

logger = logging.getLogger("app.workers.embedding_tasks")


def _select_reembed_candidates(db: Session, limit: int) -> list[Document]:
    """Pick up to ``limit`` documents that need re-embedding.

    Two independent reasons qualify a document:

    * it has at least one chunk with ``needs_reembedding=True`` (the
      embedding provider was down or fell back to a hash at processing
      time, see ``document_embedding_pipeline``);
    * its overall ``Document.confidence`` is below
      ``settings.reembed_low_confidence_threshold`` (OCR produced poor
      text and there is a real chance the new OCR/pre-processing stack
      will do better).

    We only look at non-deleted, non-duplicate documents that are not
    already in a transient state (``pending`` / ``processing``).
    """

    needs_case = case((DocumentChunk.needs_reembedding.is_(True), 1), else_=0)
    stats_subq = (
        select(
            DocumentChunk.document_id.label("document_id"),
            func.coalesce(func.sum(needs_case), 0).label("chunks_needing"),
        )
        .group_by(DocumentChunk.document_id)
        .subquery()
    )

    stmt = (
        select(Document, stats_subq.c.chunks_needing)
        .outerjoin(stats_subq, Document.id == stats_subq.c.document_id)
        .where(Document.deleted_at.is_(None))
        .where(Document.status.notin_(["pending", "processing", "duplicate"]))
        .where(
            or_(
                stats_subq.c.chunks_needing > 0,
                Document.confidence.is_not(None),
                Document.needs_reembedding.is_(True),
            )
        )
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).all())


def _is_low_ocr_confidence(document: Document) -> bool:
    confidence = document.confidence
    if confidence is None:
        return False
    return float(confidence) < float(settings.reembed_low_confidence_threshold)


def _enqueue_reembed_only(db: Session, document: Document) -> None:
    """Run the cheap re-embed path for a document.

    Calls ``reembed_document`` inline (synchronous embedding) and
    invalidates the search cache. We avoid re-queueing to Celery here
    because the whole point of this task is to pick up docs whose
    embeddings previously failed and to retry them *now*. Doing the
    embedding in-line also gives us better back-pressure: a slow
    provider just slows this task down, instead of stacking up a pile of
    re-embed jobs in the queue.
    """

    from app.services.document_embedding_pipeline import reembed_document

    result = reembed_document(db, document.id)
    logger.info(
        "Re-embed worker: document_id=%s updated=%s needs_reembedding=%s provider=%s",
        document.id,
        result["chunks_updated"],
        result["chunks_needing_reembedding"],
        result["provider"],
    )
    cache_service.invalidate_search_cache()


def _enqueue_reocr(db: Session, document: Document) -> ExtractionJob:
    """Enqueue a full reprocess (re-OCR + re-embed) on the heavy queue.

    We deliberately do **not** run the OCR synchronously here: the heavy
    queue has its own concurrency cap and prioritisation, and blocking
    this maintenance tick on a 30-second OCR run defeats the purpose of
    a periodic sweeper.
    """

    from app.workers.tasks import process_document_task

    document.status = "pending"
    document.quality_status = "pending"
    document.quality_flags_json = []
    document.error_message = None
    job = ExtractionJob(document_id=document.id, job_type="reprocess", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    cache_service.invalidate_search_cache()
    process_document_task.apply_async(
        args=(document.id, job.id),
        queue=queue_for_document(document, job.job_type),
    )
    return job


@celery_app.task(name="app.workers.embedding_tasks.reembed_pending_documents_task")
def reembed_pending_documents_task() -> dict:
    """Beat entry point: drain the queue of docs needing re-embed/re-OCR.

    Thin wrapper around :func:`run_reembed_pending_documents` that
    opens a session via ``SessionLocal``. The body is kept in a
    separate function so unit tests can drive it with an in-memory
    SQLite engine (see ``tests/test_reembed_pending_task.py``).
    """
    db: Session = SessionLocal()
    try:
        return run_reembed_pending_documents(db)
    finally:
        db.close()


def run_reembed_pending_documents(db: Session) -> dict:
    """Pure logic for the periodic re-embed / re-OCR sweep.

    Each tick we look at most ``reembed_batch_size`` documents. Of those,
    the ones with low OCR confidence are routed to the heavy queue
    (capped per tick by ``reembed_reocr_per_tick``); the rest are
    re-embedded inline.

    Returns a small dict so it shows up in Celery's result backend for
    observability (``{"inspected": N, "reembedded": X, "reocr_queued": Y}``).
    """

    if not settings.reembed_enabled:
        return {"inspected": 0, "reembedded": 0, "reocr_queued": 0, "skipped": "disabled"}

    inspected = 0
    reembedded = 0
    reocr_queued = 0
    errors = 0
    try:
        candidates = _select_reembed_candidates(db, settings.reembed_batch_size)
        inspected = len(candidates)

        for document, _chunks_needing in candidates:
            try:
                if _is_low_ocr_confidence(document) and reocr_queued < settings.reembed_reocr_per_tick:
                    _enqueue_reocr(db, document)
                    reocr_queued += 1
                else:
                    _enqueue_reembed_only(db, document)
                    reembedded += 1
            except Exception as exc:  # noqa: BLE001 - never let one doc kill the tick
                errors += 1
                db.rollback()
                logger.warning(
                    "Re-embed worker: failed for document_id=%s: %s",
                    document.id,
                    exc,
                )

        logger.info(
            "Re-embed worker tick: inspected=%s reembedded=%s reocr_queued=%s errors=%s",
            inspected,
            reembedded,
            reocr_queued,
            errors,
        )
        return {
            "inspected": inspected,
            "reembedded": reembedded,
            "reocr_queued": reocr_queued,
            "errors": errors,
        }
    except Exception as exc:  # noqa: BLE001 - never let the whole tick die
        logger.exception("Re-embed worker tick crashed: %s", exc)
        return {"inspected": inspected, "reembedded": reembedded, "reocr_queued": reocr_queued, "errors": errors + 1}


# ---------------------------------------------------------------------------
# Engine-version re-OCR sweep
# ---------------------------------------------------------------------------
# When an operator bumps ``settings.current_ocr_engine_version`` (e.g. after
# upgrading PaddleOCR), every page that was processed with the old version
# is now stale: it may be missing the new model's accuracy improvements. The
# sweep below finds documents that have at least one page stamped with an
# older version and re-runs the full processing pipeline on them so the new
# engine version is recorded on every page.


def _select_stale_engine_documents(
    db: Session,
    current_version: str,
    limit: int,
) -> list[int]:
    """Return the IDs of documents that have at least one page with a stale
    ``ocr_engine_version``.

    We exclude documents that are already in a transient state
    (``pending`` / ``processing``) so we do not enqueue a second job on
    top of one that is already running, and we exclude soft-deleted and
    duplicate documents because there is no point re-OCR'ing them.
    """
    if not current_version:
        return []

    stmt = (
        select(DocumentPage.document_id)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(Document.status.notin_(["pending", "processing", "duplicate"]))
        .where(
            or_(
                DocumentPage.ocr_engine_version.is_(None),
                DocumentPage.ocr_engine_version != current_version,
            )
        )
        .group_by(DocumentPage.document_id)
        .order_by(DocumentPage.document_id.asc())
        .limit(limit)
    )
    return [row[0] for row in db.execute(stmt).all()]


def _enqueue_versioned_reocr(db: Session, document: Document) -> ExtractionJob:
    """Enqueue a full reprocess for a document whose pages are stale.

    Mirrors :func:`_enqueue_reocr` so the heavy queue gets a single
    ``reprocess`` job per document; the processing task will refresh
    ``ocr_engine_version`` on every page as it goes.
    """

    from app.workers.tasks import process_document_task

    document.status = "pending"
    document.quality_status = "pending"
    document.quality_flags_json = []
    document.error_message = None
    job = ExtractionJob(document_id=document.id, job_type="reprocess", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    cache_service.invalidate_search_cache()
    process_document_task.apply_async(
        args=(document.id, job.id),
        queue=queue_for_document(document, job.job_type),
    )
    return job


def run_reprocess_with_new_ocr_engine(db: Session) -> dict:
    """Pure logic for the engine-version re-OCR sweep.

    Returns a small dict so it shows up in Celery's result backend for
    observability (``{"inspected": N, "queued": X, "current": "v"}``).
    """

    if not settings.ocr_reprocess_on_version_drift:
        return {
            "inspected": 0,
            "queued": 0,
            "skipped": "disabled",
            "current_version": settings.current_ocr_engine_version,
        }

    current_version = settings.current_ocr_engine_version
    inspected = 0
    queued = 0
    errors = 0
    try:
        candidate_ids = _select_stale_engine_documents(
            db,
            current_version,
            limit=settings.reocr_versioned_per_tick,
        )
        inspected = len(candidate_ids)

        for document_id in candidate_ids:
            if queued >= settings.reocr_versioned_per_tick:
                break
            try:
                document = db.get(Document, document_id)
                if document is None:
                    continue
                _enqueue_versioned_reocr(db, document)
                queued += 1
            except Exception as exc:  # noqa: BLE001 - never let one doc kill the tick
                errors += 1
                db.rollback()
                logger.warning(
                    "Versioned re-OCR worker: failed for document_id=%s: %s",
                    document_id,
                    exc,
                )

        logger.info(
            "Versioned re-OCR worker tick: current=%s inspected=%s queued=%s errors=%s",
            current_version,
            inspected,
            queued,
            errors,
        )
        return {
            "inspected": inspected,
            "queued": queued,
            "errors": errors,
            "current_version": current_version,
        }
    except Exception as exc:  # noqa: BLE001 - never let the whole tick die
        logger.exception("Versioned re-OCR worker tick crashed: %s", exc)
        return {
            "inspected": inspected,
            "queued": queued,
            "errors": errors + 1,
            "current_version": current_version,
        }


@celery_app.task(name="app.workers.embedding_tasks.reprocess_with_new_ocr_engine_task")
def reprocess_with_new_ocr_engine_task() -> dict:
    """Beat entry point: re-OCR documents whose pages were processed with
    a stale engine version.

    Thin wrapper around :func:`run_reprocess_with_new_ocr_engine` that
    opens a session via ``SessionLocal``. The body is kept in a
    separate function so unit tests can drive it with an in-memory
    SQLite engine (see ``tests/test_reprocess_with_new_ocr_engine.py``).
    """
    db: Session = SessionLocal()
    try:
        return run_reprocess_with_new_ocr_engine(db)
    finally:
        db.close()
