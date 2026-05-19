from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ExtractionJob
from app.services.cache import cache_service

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
    job.status = "cancelled"
    job.finished_at = datetime.utcnow()
    job.error_message = "Cancelled by admin"
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
    stmt = select(func.count()).select_from(ExtractionJob).where(ExtractionJob.status == status)
    if queue_prefix == "embeddings":
        stmt = stmt.where(ExtractionJob.job_type.ilike("%embeddings%"))
    elif queue_prefix == "ocr_heavy":
        stmt = stmt.where(ExtractionJob.job_type.not_ilike("%embeddings%"))
    elif queue_prefix == "text_fast":
        stmt = stmt.where(ExtractionJob.job_type.not_ilike("%embeddings%"))
    elif queue_prefix == "maintenance":
        stmt = stmt.where(ExtractionJob.job_type.ilike("%maintenance%"))
    return int(db.scalar(stmt) or 0)


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
