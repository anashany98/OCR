from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.stability import is_allowed_file_path, is_file_stable, is_ignored_path
from app.models import Document, User
from app.services.document_service import register_existing_file
from app.services.file_storage import calculate_sha256
from app.services.ingestion_events import path_metadata, record_ingestion_event, upsert_watched_file
from app.services.queue_control import is_ingestion_paused, should_accept_more_jobs

DEFAULT_SUBFOLDERS = ["presupuestos", "pedidos", "facturas", "planos", "imagenes", "otros"]


def scan_input_folders(
    db: Session, *, user: User | None = None, enqueue: bool = True, limit: int | None = None
) -> dict:
    settings.input_dir.mkdir(parents=True, exist_ok=True)
    for folder in DEFAULT_SUBFOLDERS:
        (settings.input_dir / folder).mkdir(parents=True, exist_ok=True)

    scanned = 0
    registered = 0
    duplicates = 0
    skipped = 0
    unstable = 0
    failed = 0
    ignored = 0
    paused = 0
    backpressure = 0

    for path in _iter_files(settings.input_dir):
        if limit is not None and registered >= limit:
            break
        scanned += 1
        source_path = str(path)
        if is_ingestion_paused():
            _record_path_status(db, path, "paused")
            db.commit()
            paused += 1
            break
        if not should_accept_more_jobs(db):
            size_bytes, mtime_epoch = path_metadata(path)
            watched = upsert_watched_file(
                db,
                path=source_path,
                status="backpressure",
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
            )
            record_ingestion_event(
                db,
                event_type="backpressure",
                source_path=source_path,
                watched_file=watched,
                details={"max_pending_jobs": settings.ingestion_max_pending_jobs},
            )
            db.commit()
            backpressure += 1
            break
        if not is_allowed_file_path(path):
            size_bytes, mtime_epoch = path_metadata(path)
            watched = upsert_watched_file(
                db,
                path=source_path,
                status="ignored",
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
            )
            record_ingestion_event(
                db,
                event_type="ignored",
                source_path=source_path,
                watched_file=watched,
                details={"reason": "extension_not_allowed"},
            )
            db.commit()
            ignored += 1
            continue
        if not is_file_stable(path, settings.ingestion_stable_seconds):
            _record_path_status(
                db, path, "unstable", details={"stable_seconds": settings.ingestion_stable_seconds}
            )
            db.commit()
            unstable += 1
            continue
        existing_document = db.scalar(
            select(Document)
            .where(Document.source_path == source_path)
            .order_by(Document.id.desc())
            .limit(1)
        )
        if existing_document:
            current_hash = calculate_sha256(path)
            if existing_document.file_hash == current_hash:
                _record_path_status(
                    db,
                    path,
                    "skipped",
                    document_id=existing_document.id,
                    details={"reason": "source_path_already_registered"},
                )
                db.commit()
                skipped += 1
                continue
            _record_path_status(
                db,
                path,
                "modified",
                document_id=existing_document.id,
                details={"previous_hash": existing_document.file_hash, "new_hash": current_hash},
            )
            db.commit()
        try:
            document, _ = register_existing_file(
                db,
                source=path,
                original_filename=path.name,
                source_path=source_path,
                user=user,
                enqueue=enqueue,
            )
        except Exception as exc:
            db.rollback()
            size_bytes, mtime_epoch = path_metadata(path)
            watched = upsert_watched_file(
                db,
                path=source_path,
                status="failed",
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
                error_message=str(exc),
            )
            record_ingestion_event(
                db,
                event_type="failed",
                source_path=source_path,
                watched_file=watched,
                error_message=str(exc),
            )
            db.commit()
            failed += 1
            continue
        registered += 1
        if document.status == "duplicate":
            duplicates += 1

    return {
        "scanned": scanned,
        "registered": registered,
        "duplicates": duplicates,
        "skipped": skipped,
        "unstable": unstable,
        "failed": failed,
        "ignored": ignored,
        "paused": paused,
        "backpressure": backpressure,
    }


def _record_path_status(
    db: Session,
    path: Path,
    status: str,
    *,
    document_id: int | None = None,
    job_id: int | None = None,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    size_bytes, mtime_epoch = path_metadata(path)
    watched = upsert_watched_file(
        db,
        path=str(path),
        status=status,
        size_bytes=size_bytes,
        mtime_epoch=mtime_epoch,
        document_id=document_id,
        job_id=job_id,
        error_message=error_message,
    )
    record_ingestion_event(
        db,
        event_type=status,
        source_path=str(path),
        document_id=document_id,
        job_id=job_id,
        watched_file=watched,
        details=details,
        error_message=error_message,
    )


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and not is_ignored_path(path):
            yield path
