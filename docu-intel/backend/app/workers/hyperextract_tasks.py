"""MiniMax M3 (FASE 3) — Hyper-Extract Celery tasks.

This module owns the two Celery tasks that route Hyper-Extract
work to the dedicated ``hyperextract`` queue. The queue is
configured in :mod:`app.workers.celery_app` and is intentionally
low-priority so enrichment cannot starve the OCR path or the
chat path.

The pipeline in :mod:`app.services.document_processing_core`
already runs ``_maybe_run_hyperextract`` inline. The Celery
tasks in this module are an alternative entry point used by:

* the operator-driven "retry failed extractions" button on the
  admin panel (lower-priority than interactive, but still
  asynchronous so the UI does not block);
* the periodic backfill that retries documents whose previous
  extraction failed or whose fingerprint changed.

The tasks delegate to the same :func:`_maybe_run_hyperextract`
helper so the idempotence contract (fingerprint, success-only
reuse, no-reuse-on-failure) is preserved.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.workers.celery_app import celery_app

logger = logging.getLogger("app.workers.hyperextract_tasks")


@celery_app.task(
    name="app.workers.hyperextract_tasks.enqueue_hyperextract_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def enqueue_hyperextract_task(self, document_id: int) -> dict:
    """Run the structured-extraction stage for a single document.

    The task is enqueued from the admin endpoint, the periodic
    backfill or the post-OCR webhook. The work is identical to
    the in-pipeline path; routing through Celery simply means
    the LLM call cannot block an interactive request.
    """
    from app.database.session import SessionLocal
    from app.models.document import Document
    from app.services.document_processing_core import _maybe_run_hyperextract

    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            return {"document_id": document_id, "status": "skipped", "reason": "missing"}
        text = ""
        if document.pages:
            text = "\n".join(p.text for p in document.pages if p.text)
        _maybe_run_hyperextract(
            db,
            document,
            text=text,
            document_type=document.document_type,
        )
        db.commit()
        return {"document_id": document_id, "status": "completed"}
    except Exception as exc:
        db.rollback()
        logger.warning(
            "hyperextract_task_failed document_id=%s attempt=%s error=%s",
            document_id,
            self.request.retries,
            exc,
        )
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="app.workers.hyperextract_tasks.replay_failed_extractions_task",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
    acks_late=True,
)
def replay_failed_extractions_task(
    self, *, max_age_minutes: int = 60, limit: int = 50
) -> dict:
    """Replay recent failed extractions on a low-priority schedule.

    The task reads the last ``max_age_minutes`` of
    ``DocumentExtraction`` rows tagged ``failed`` and re-enqueues
    them on the same ``hyperextract`` queue. The fingerprint
    check inside :func:`_maybe_run_hyperextract` is the
    authoritative gate; a row whose text has not changed will
    still fail the same way, but a transient provider outage
    (timeout, network blip) gets a clean retry.
    """
    from sqlalchemy import select

    from app.database.session import SessionLocal
    from app.models import Document, DocumentExtraction

    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        rows = list(
            db.scalars(
                select(DocumentExtraction)
                .where(
                    DocumentExtraction.status == "failed",
                    DocumentExtraction.updated_at >= cutoff,
                )
                .order_by(DocumentExtraction.id.desc())
                .limit(limit)
            ).all()
        )
        for row in rows:
            document = db.get(Document, row.document_id)
            if document is None or document.deleted_at is not None:
                continue
            enqueue_hyperextract_task.delay(document.id)
        return {"replayed": len(rows)}
    except Exception as exc:
        logger.warning("replay_failed_extractions_failed error=%s", exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
