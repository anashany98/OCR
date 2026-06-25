from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionEvent, WatchedFile


def path_metadata(path: Path) -> tuple[int | None, float | None]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None, None
    return stat.st_size, stat.st_mtime


def upsert_watched_file(
    db: Session,
    *,
    path: str,
    status: str,
    size_bytes: int | None = None,
    mtime_epoch: float | None = None,
    document_id: int | None = None,
    job_id: int | None = None,
    error_message: str | None = None,
) -> WatchedFile:
    watched = db.scalar(select(WatchedFile).where(WatchedFile.path == path))
    now = datetime.now(UTC)
    if not watched:
        watched = WatchedFile(path=path, first_seen_at=now)
        db.add(watched)
    watched.status = status
    watched.size_bytes = size_bytes
    watched.mtime_epoch = mtime_epoch
    watched.last_seen_at = now
    watched.document_id = document_id if document_id is not None else watched.document_id
    watched.job_id = job_id if job_id is not None else watched.job_id
    watched.error_message = error_message
    db.flush()
    return watched


def record_ingestion_event(
    db: Session,
    *,
    event_type: str,
    source_path: str | None = None,
    document_id: int | None = None,
    job_id: int | None = None,
    watched_file: WatchedFile | None = None,
    details: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> IngestionEvent:
    event = IngestionEvent(
        event_type=event_type,
        source_path=source_path,
        document_id=document_id,
        job_id=job_id,
        watched_file_id=watched_file.id if watched_file else None,
        details_json=details,
        error_message=error_message,
    )
    db.add(event)
    db.flush()
    return event
