from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, DocumentPage, ExtractionJob, IngestionEvent, WatchedFile
from app.services.ocr_page_roles import ocr_applicable_clause
from app.services.queue_control import build_queue_control_status


def build_operations_status(db: Session) -> dict:
    return {
        "jobs_by_status": _group_count(db, ExtractionJob.status, ExtractionJob),
        "watched_files_by_status": _group_count(db, WatchedFile.status, WatchedFile),
        "ingestion_events_by_type": _group_count(db, IngestionEvent.event_type, IngestionEvent),
        "disk": {
            "input_dir": _disk_usage(settings.input_dir),
            "files_dir": _disk_usage(settings.files_dir),
        },
    }


def build_operations_overview(db: Session) -> dict:
    total_bytes = int(
        db.scalar(
            select(func.coalesce(func.sum(Document.file_size), 0)).where(
                Document.deleted_at.is_(None)
            )
        )
        or 0
    )
    pending_or_processing = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
        or 0
    )
    processed_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status == "processed")
        )
        or 0
    )
    finished_jobs = list(
        db.scalars(
            select(ExtractionJob)
            .where(ExtractionJob.status == "processed")
            .where(ExtractionJob.started_at.is_not(None))
            .where(ExtractionJob.finished_at.is_not(None))
            .order_by(ExtractionJob.finished_at.desc())
            .limit(200)
        ).all()
    )
    durations = [
        (job.finished_at - job.started_at).total_seconds()
        for job in finished_jobs
        if job.finished_at and job.started_at and job.finished_at >= job.started_at
    ]
    avg_seconds = sum(durations) / len(durations) if durations else 0.0
    last_sources = [
        {
            "source_path": row.path,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "status": row.status,
        }
        for row in db.scalars(
            select(WatchedFile).order_by(WatchedFile.updated_at.desc()).limit(10)
        ).all()
    ]
    low_ocr_pages = int(
        db.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .join(Document, Document.id == DocumentPage.document_id)
            .where(Document.deleted_at.is_(None))
            .where(ocr_applicable_clause(DocumentPage.ocr_content_kind))
            .where(DocumentPage.ocr_confidence.is_not(None))
            .where(DocumentPage.ocr_confidence < settings.low_ocr_confidence_threshold)
            .where(DocumentPage.review_status != "approved")
        )
        or 0
    )
    queue_status = build_queue_control_status(db)
    return {
        "documents": {
            "by_status": _group_count(db, Document.status, Document),
            "by_quality_status": _group_count(db, Document.quality_status, Document),
            "total_size_bytes": total_bytes,
            "low_ocr_pages": low_ocr_pages,
        },
        "jobs": {
            "by_status": _group_count(db, ExtractionJob.status, ExtractionJob),
            "pending_or_processing": pending_or_processing,
            "processed_total": processed_jobs,
            "avg_processing_seconds": round(avg_seconds, 2),
            "estimated_remaining_seconds": round(avg_seconds * pending_or_processing, 2)
            if avg_seconds
            else None,
        },
        "watcher": {
            "by_status": _group_count(db, WatchedFile.status, WatchedFile),
            "last_sources": last_sources,
        },
        "queues": queue_status.__dict__,
        "disk": {
            "input_dir": _disk_usage(settings.input_dir),
            "files_dir": _disk_usage(settings.files_dir),
        },
    }


def build_maintenance_report(db: Session) -> dict:
    failed_jobs = int(
        db.scalar(
            select(func.count()).select_from(ExtractionJob).where(ExtractionJob.status == "failed")
        )
        or 0
    )
    watched_failed = int(
        db.scalar(
            select(func.count()).select_from(WatchedFile).where(WatchedFile.status == "failed")
        )
        or 0
    )
    return {
        "checks": [
            {
                "key": "failed_jobs",
                "status": "warning" if failed_jobs else "ok",
                "count": failed_jobs,
            },
            {
                "key": "failed_watched_files",
                "status": "warning" if watched_failed else "ok",
                "count": watched_failed,
            },
        ],
        "disk": {
            "input_dir": _disk_usage(settings.input_dir),
            "files_dir": _disk_usage(settings.files_dir),
        },
    }


def _group_count(db: Session, column, model) -> dict[str, int]:
    return {
        str(key or "unknown"): int(count)
        for key, count in db.execute(
            select(column, func.count()).select_from(model).group_by(column)
        ).all()
    }


def _disk_usage(path: Path) -> dict:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        usage = shutil.disk_usage(Path.cwd())
    return {
        "path": str(path),
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
    }
