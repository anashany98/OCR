from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import setup_logging
from app.database.session import SessionLocal
from app.ingestion.scanner import DEFAULT_SUBFOLDERS, scan_input_folders
from app.ingestion.stability import is_allowed_file_path, is_file_stable, is_ignored_path
from app.models import Document
from app.services.document_service import register_existing_file
from app.services.ingestion_events import path_metadata, record_ingestion_event, upsert_watched_file
from app.services.queue_control import is_ingestion_paused, should_accept_more_jobs

logger = logging.getLogger("app.ingestion.watcher")


@dataclass
class PendingFileRegistry:
    _paths: dict[Path, float] = field(default_factory=dict)

    def add(self, path: Path, *, now: float | None = None) -> None:
        if is_ignored_path(path):
            return
        self._paths[path] = time.monotonic() if now is None else now

    def discard(self, path: Path) -> None:
        self._paths.pop(path, None)

    def ready_paths(self, *, now: float | None = None, settle_seconds: float = 5.0, limit: int = 10) -> list[Path]:
        current_time = time.monotonic() if now is None else now
        ready = [
            path
            for path, last_event_at in sorted(self._paths.items(), key=lambda item: item[1])
            if current_time - last_event_at >= settle_seconds
        ]
        return ready[:limit]

    def __len__(self) -> int:
        return len(self._paths)


def ingest_path_if_ready(db: Session, path: Path, *, enqueue: bool = True) -> dict:
    if is_ignored_path(path):
        _record_path_status(db, path, "ignored", details={"reason": "ignored_path"})
        db.commit()
        return {"status": "ignored", "path": str(path)}
    if not is_allowed_file_path(path):
        _record_path_status(db, path, "ignored", details={"reason": "extension_not_allowed"})
        db.commit()
        return {"status": "ignored", "path": str(path)}
    if is_ingestion_paused():
        _record_path_status(db, path, "paused")
        db.commit()
        return {"status": "paused", "path": str(path)}
    if not should_accept_more_jobs(db):
        _record_path_status(db, path, "backpressure", details={"max_pending_jobs": settings.ingestion_max_pending_jobs})
        db.commit()
        return {"status": "backpressure", "path": str(path)}
    if not path.exists() or not path.is_file():
        _record_path_status(db, path, "missing")
        db.commit()
        return {"status": "missing", "path": str(path)}
    if not is_file_stable(path, settings.ingestion_stable_seconds):
        _record_path_status(db, path, "unstable", details={"stable_seconds": settings.ingestion_stable_seconds})
        db.commit()
        return {"status": "unstable", "path": str(path)}

    source_path = str(path)
    existing_document_id = db.scalar(select(Document.id).where(Document.source_path == source_path).limit(1))
    if existing_document_id:
        _record_path_status(
            db,
            path,
            "skipped",
            document_id=existing_document_id,
            details={"reason": "source_path_already_registered"},
        )
        db.commit()
        return {"status": "skipped", "path": source_path, "document_id": existing_document_id}

    document, job = register_existing_file(
        db,
        source=path,
        original_filename=path.name,
        source_path=source_path,
        user=None,
        enqueue=enqueue,
    )
    return {
        "status": document.status,
        "path": source_path,
        "document_id": document.id,
        "job_id": job.id if job else None,
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


def process_pending_paths(db: Session, pending: PendingFileRegistry, *, enqueue: bool = True) -> dict:
    counts = {
        "processed": 0,
        "duplicates": 0,
        "skipped": 0,
        "unstable": 0,
        "failed": 0,
        "missing": 0,
        "ignored": 0,
        "paused": 0,
        "backpressure": 0,
    }
    ready = pending.ready_paths(
        settle_seconds=settings.watcher_settle_seconds,
        limit=settings.watcher_max_files_per_tick,
    )
    for path in ready:
        try:
            result = ingest_path_if_ready(db, path, enqueue=enqueue)
        except Exception as exc:
            db.rollback()
            try:
                _record_path_status(db, path, "failed", error_message=str(exc))
                db.commit()
            except Exception:
                db.rollback()
            counts["failed"] += 1
            pending.discard(path)
            logger.exception("failed_to_ingest path=%s", path)
            continue

        status = result["status"]
        if status == "unstable":
            counts["unstable"] += 1
            continue
        if status in {"paused", "backpressure"}:
            counts[status] += 1
            continue
        pending.discard(path)
        if status == "duplicate":
            counts["duplicates"] += 1
        elif status in {"skipped", "ignored"}:
            counts[status] += 1
        elif status == "missing":
            counts["missing"] += 1
        else:
            counts["processed"] += 1
    return counts


def enqueue_existing_files(pending: PendingFileRegistry, root: Path) -> int:
    added = 0
    for path in root.rglob("*"):
        if path.is_file() and not is_ignored_path(path) and is_allowed_file_path(path):
            pending.add(path)
            added += 1
    return added


class _WatchdogEventHandler:
    def __init__(self, pending: PendingFileRegistry):
        from watchdog.events import FileSystemEventHandler

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                self._add_event_path(event)

            def on_modified(self, event):
                self._add_event_path(event)

            def on_moved(self, event):
                if not event.is_directory:
                    pending.add(Path(event.dest_path))

            def _add_event_path(self, event):
                if not event.is_directory:
                    pending.add(Path(event.src_path))

        self.handler = Handler()


def run_watch_loop() -> None:
    if settings.watcher_backend == "polling":
        from watchdog.observers.polling import PollingObserver as Observer

        observer = Observer(timeout=settings.watcher_poll_seconds)
    else:
        from watchdog.observers import Observer

        observer = Observer()

    settings.input_dir.mkdir(parents=True, exist_ok=True)
    for folder in DEFAULT_SUBFOLDERS:
        (settings.input_dir / folder).mkdir(parents=True, exist_ok=True)

    pending = PendingFileRegistry()
    initial_count = enqueue_existing_files(pending, settings.input_dir)
    logger.info("watcher_initial_pending count=%s input_dir=%s", initial_count, settings.input_dir)

    observer.schedule(_WatchdogEventHandler(pending).handler, str(settings.input_dir), recursive=settings.watcher_recursive)
    observer.start()

    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    last_rescan_at = time.monotonic()
    try:
        while not stop_requested and settings.watcher_enabled:
            db = SessionLocal()
            try:
                counts = process_pending_paths(db, pending, enqueue=True)
                if any(counts.values()):
                    logger.info("watcher_tick pending=%s counts=%s", len(pending), counts)
                if time.monotonic() - last_rescan_at >= settings.watcher_rescan_interval_seconds:
                    result = scan_input_folders(db, user=None, enqueue=True)
                    logger.info("watcher_rescan result=%s", result)
                    last_rescan_at = time.monotonic()
            finally:
                db.close()
            time.sleep(settings.watcher_poll_seconds)
    finally:
        observer.stop()
        observer.join(timeout=10)


def main() -> None:
    setup_logging()
    if not settings.watcher_enabled:
        logger.info("watcher_disabled")
        return
    run_watch_loop()


if __name__ == "__main__":
    main()
