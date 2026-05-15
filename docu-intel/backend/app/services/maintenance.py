from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ExtractionJob, IngestionEvent, WatchedFile


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


def build_maintenance_report(db: Session) -> dict:
    failed_jobs = int(db.scalar(select(func.count()).select_from(ExtractionJob).where(ExtractionJob.status == "failed")) or 0)
    watched_failed = int(db.scalar(select(func.count()).select_from(WatchedFile).where(WatchedFile.status == "failed")) or 0)
    return {
        "checks": [
            {"key": "failed_jobs", "status": "warning" if failed_jobs else "ok", "count": failed_jobs},
            {"key": "failed_watched_files", "status": "warning" if watched_failed else "ok", "count": watched_failed},
        ],
        "disk": {
            "input_dir": _disk_usage(settings.input_dir),
            "files_dir": _disk_usage(settings.files_dir),
        },
    }


def _group_count(db: Session, column, model) -> dict[str, int]:
    return {str(key or "unknown"): int(count) for key, count in db.execute(select(column, func.count()).select_from(model).group_by(column)).all()}


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
