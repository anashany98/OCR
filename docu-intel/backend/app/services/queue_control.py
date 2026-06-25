from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, ExtractionJob
from app.services.cache import cache_service
from app.workers.routing import queue_for_document

INGESTION_PAUSED_KEY = "operations:ingestion_paused"


@dataclass(frozen=True)
class QueueControlStatus:
    ingestion_paused: bool
    pending_jobs: int
    processing_jobs: int
    max_pending_jobs: int
    backpressure_active: bool
    queues: dict[str, dict[str, int]]


def pause_ingestion() -> None:
    _set_flag(True)


def resume_ingestion() -> None:
    _set_flag(False)


def is_ingestion_paused() -> bool:
    return _get_flag()


def should_accept_more_jobs(db: Session) -> bool:
    if is_ingestion_paused():
        return False
    return _active_job_count(db) < settings.ingestion_max_pending_jobs


def build_queue_control_status(db: Session) -> QueueControlStatus:
    pending = _count_jobs(db, "pending")
    processing = _count_jobs(db, "processing")
    queues = {
        queue: {
            "pending": _count_jobs(db, "pending", queue_prefix=queue),
            "processing": _count_jobs(db, "processing", queue_prefix=queue),
            "failed": _count_jobs(db, "failed", queue_prefix=queue),
        }
        for queue in ("text_fast", "ocr_heavy", "embeddings", "maintenance")
    }
    return QueueControlStatus(
        ingestion_paused=is_ingestion_paused(),
        pending_jobs=pending,
        processing_jobs=processing,
        max_pending_jobs=settings.ingestion_max_pending_jobs,
        backpressure_active=pending + processing >= settings.ingestion_max_pending_jobs,
        queues=queues,
    )


def cancel_pending_job(db: Session, job: ExtractionJob) -> ExtractionJob:
    if job.status not in {"pending", "failed"}:
        raise ValueError("Only pending or failed jobs can be cancelled safely")
    document = job.document or db.get(Document, job.document_id)
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    job.error_message = "Cancelled by admin"
    if document and _should_restore_document_after_cancel(db, document, job):
        if document.quality_status == "needs_human_review":
            document.status = "needs_review"
        else:
            document.status = "processed"
        document.error_message = None
    db.flush()
    return job


def _active_job_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
        or 0
    )


def _count_jobs(db: Session, status: str, *, queue_prefix: str | None = None) -> int:
    stmt = (
        select(ExtractionJob, Document)
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(ExtractionJob.status == status)
    )
    rows = db.execute(stmt).all()
    if queue_prefix is None:
        return len(rows)
    return sum(
        1 for job, document in rows if queue_for_document(document, job.job_type) == queue_prefix
    )


def _should_restore_document_after_cancel(
    db: Session, document: Document, job: ExtractionJob
) -> bool:
    active_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.document_id == document.id)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
            .where(ExtractionJob.id != job.id)
        )
        or 0
    )
    if active_jobs > 0 or document.status != "pending":
        return False
    return document.processed_at is not None or document.quality_status == "needs_human_review"


def _set_flag(value: bool) -> None:
    try:
        if value:
            cache_service.client.set(INGESTION_PAUSED_KEY, "1")
        else:
            cache_service.client.delete(INGESTION_PAUSED_KEY)
    except Exception:
        _memory_flags[INGESTION_PAUSED_KEY] = value


def _get_flag() -> bool:
    try:
        return bool(cache_service.client.get(INGESTION_PAUSED_KEY))
    except Exception:
        return bool(_memory_flags.get(INGESTION_PAUSED_KEY))


_memory_flags: dict[str, bool] = {}
