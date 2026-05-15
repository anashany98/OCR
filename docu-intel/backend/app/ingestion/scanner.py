from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.stability import is_file_stable, is_ignored_path
from app.models import Document, User
from app.services.document_service import register_existing_file
from app.services.ingestion_events import path_metadata, record_ingestion_event, upsert_watched_file

DEFAULT_SUBFOLDERS = ["presupuestos", "pedidos", "facturas", "planos", "imagenes", "otros"]


def scan_input_folders(db: Session, *, user: User | None = None, enqueue: bool = True, limit: int | None = None) -> dict:
    settings.input_dir.mkdir(parents=True, exist_ok=True)
    for folder in DEFAULT_SUBFOLDERS:
        (settings.input_dir / folder).mkdir(parents=True, exist_ok=True)

    scanned = 0
    registered = 0
    duplicates = 0
    skipped = 0
    unstable = 0
    failed = 0

    for path in _iter_files(settings.input_dir):
        if limit is not None and registered >= limit:
            break
        scanned += 1
        source_path = str(path)
        already_registered = db.scalar(select(Document.id).where(Document.source_path == source_path).limit(1))
        if already_registered:
            size_bytes, mtime_epoch = path_metadata(path)
            watched = upsert_watched_file(
                db,
                path=source_path,
                status="skipped",
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
                document_id=already_registered,
            )
            record_ingestion_event(
                db,
                event_type="skipped",
                source_path=source_path,
                document_id=already_registered,
                watched_file=watched,
                details={"reason": "source_path_already_registered"},
            )
            db.commit()
            skipped += 1
            continue
        if not is_file_stable(path, settings.ingestion_stable_seconds):
            size_bytes, mtime_epoch = path_metadata(path)
            watched = upsert_watched_file(
                db,
                path=source_path,
                status="unstable",
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
            )
            record_ingestion_event(
                db,
                event_type="unstable",
                source_path=source_path,
                watched_file=watched,
                details={"stable_seconds": settings.ingestion_stable_seconds},
            )
            db.commit()
            unstable += 1
            continue
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
    }


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and not is_ignored_path(path):
            yield path
