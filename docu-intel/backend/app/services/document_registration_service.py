from __future__ import annotations

import mimetypes
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, ExtractionJob, User
from app.services.audit import write_audit
from app.services.budget_scope import assign_document_budget_scope
from app.services.cache import cache_service
from app.services.file_security import inspect_file_for_ingestion
from app.services.file_storage import calculate_sha256, copy_to_storage
from app.services.ingestion_events import path_metadata, record_ingestion_event, upsert_watched_file
from app.services.tenant_access import apply_folder_rules_to_document

# This module used to look up ``inspect_file_for_ingestion`` through
# a ``_facade()`` helper that reached into
# ``sys.modules["app.services.document_service"]`` at call time.
# The helper itself is imported directly (line 18); we removed
# the facade so the type checker can see the dependency.


# ---------------------------------------------------------------------------
# F0-06: path validation for untrusted client-provided relative paths
# ---------------------------------------------------------------------------

# Characters that are never valid in a safe relative POSIX path.
_WIN_DRIVE_RE = re.compile(r"^[a-zA-Z]:")
_UNC_PREFIX_RE = re.compile(r"^\\\\")
_SLASH_OR_BACKSLASH = re.compile(r"[/\\]")


def normalize_untrusted_relative_path(raw: str, *, user_id: int | None = None) -> str:
    """Validate and normalize an untrusted relative path from a client upload.

    Returns a safe POSIX relative path suitable for storage metadata.
    Raises ``ValueError`` if the path cannot be made safe.

    Rules:
    * Must be a relative path (no leading ``/`` or drive letter).
    * No ``..`` components after normalization.
    * No backslashes (Windows separators) after normalization.
    * No null bytes.
    * Optionally prefixed with ``upload/<user_id>/`` for namespace isolation.
    """
    if not raw or not raw.strip():
        raise ValueError("relative_path must not be empty")

    if "\x00" in raw:
        raise ValueError("relative_path contains null bytes")

    # Reject absolute paths and Windows drive letters
    if _WIN_DRIVE_RE.match(raw):
        raise ValueError("relative_path must not be an absolute Windows path")
    if _UNC_PREFIX_RE.match(raw):
        raise ValueError("relative_path must not be a UNC path")

    # Normalize separators to POSIX
    normalized = raw.replace("\\", "/")

    # Reject absolute paths after normalization
    if normalized.startswith("/"):
        raise ValueError("relative_path must not be absolute")

    # Build PurePosixPath to resolve . and .. components
    parts = PurePosixPath(normalized).parts

    # Check for directory traversal
    if ".." in parts:
        raise ValueError("relative_path must not contain '..' components")

    # Reconstruct clean path
    clean = str(PurePosixPath(*parts)) if parts else ""

    # Reject empty result
    if not clean or clean == ".":
        raise ValueError("relative_path resolves to empty path")

    # Namespace isolation: prefix with user directory
    if user_id is not None:
        clean = f"upload/{user_id}/{clean}"

    return clean


def _type_from_extension(extension: str) -> str:
    if extension in {".xls", ".xlsx", ".xlsm", ".csv", ".tsv"}:
        return "excel"
    if extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return "imagen"
    return "desconocido"


def register_upload(
    db: Session,
    *,
    filename: str,
    stream: BinaryIO,
    user: User | None,
    source_path: str | None = None,
    enqueue: bool = True,
) -> tuple[Document, ExtractionJob | None]:
    suffix = Path(filename).suffix.lower()
    max_upload_size_mb = settings.max_upload_size_mb
    max_bytes = max(0, int(max_upload_size_mb) * 1024 * 1024)
    bytes_written = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        temp_path = Path(tmp.name)
    try:
        with temp_path.open("wb") as tmp:
            while chunk := stream.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ValueError(f"max_upload_size exceeded: {max_upload_size_mb} MB")
                tmp.write(chunk)
        return register_existing_file(
            db,
            source=temp_path,
            original_filename=filename,
            user=user,
            source_path=source_path,
            enqueue=enqueue,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def register_existing_file(
    db: Session,
    *,
    source: Path,
    original_filename: str | None = None,
    user: User | None = None,
    source_path: str | None = None,
    enqueue: bool = True,
) -> tuple[Document, ExtractionJob | None]:
    file_hash = calculate_sha256(source)
    extension = source.suffix.lower()
    mime_type, _ = mimetypes.guess_type(str(source))
    security_result = inspect_file_for_ingestion(source)
    existing = db.scalar(
        select(Document)
        .where(Document.file_hash == file_hash)
        .where(Document.status.notin_(["duplicate", "failed"]))
        .where(Document.deleted_at.is_(None))
        .order_by(Document.id.asc())
    )

    stored_filename: str | None = None
    status = "pending"
    duplicate_of_document_id: int | None = None
    if existing:
        if existing.status in {"processed", "needs_review"}:
            if source_path:
                size_bytes, mtime_epoch = path_metadata(source)
                watched = upsert_watched_file(
                    db,
                    path=source_path,
                    status="deduplicated",
                    size_bytes=size_bytes,
                    mtime_epoch=mtime_epoch,
                    document_id=existing.id,
                )
                record_ingestion_event(
                    db,
                    event_type="deduplicated",
                    source_path=source_path,
                    document_id=existing.id,
                    watched_file=watched,
                    details={
                        "reason": "sha_dedup_existing_processed",
                        "existing_document_id": existing.id,
                    },
                )
                db.commit()
            return existing, None
        status = "duplicate"
        duplicate_of_document_id = existing.id
        stored_filename = existing.stored_filename
    else:
        stored_filename = str(
            copy_to_storage(
                source,
                settings.files_dir,
                file_hash,
                extension,
                strategy=settings.file_storage_strategy,
            )
        )
        if not security_result.allowed:
            status = "needs_review"

    document = Document(
        original_filename=original_filename or source.name,
        stored_filename=stored_filename,
        source_path=source_path,
        file_hash=file_hash,
        mime_type=mime_type,
        extension=extension,
        file_size=source.stat().st_size,
        document_type=_type_from_extension(extension),
        status=status,
        quality_status="needs_human_review"
        if status == "needs_review"
        else ("duplicate" if status == "duplicate" else "pending"),
        quality_score=0.0 if status == "needs_review" else None,
        quality_flags_json=[f"security:{security_result.reason}"]
        if not security_result.allowed
        else [],
        error_message=f"File quarantined: {security_result.reason}"
        if not security_result.allowed
        else None,
        duplicate_of_document_id=duplicate_of_document_id,
    )
    db.add(document)
    db.flush()
    assign_document_budget_scope(db, document)
    apply_folder_rules_to_document(db, document)

    job: ExtractionJob | None = None
    if status not in {"duplicate", "needs_review"}:
        job = ExtractionJob(document_id=document.id, job_type="extract", status="pending")
        db.add(job)
        db.flush()

    write_audit(
        db,
        user=user,
        action="document_quarantined" if status == "needs_review" else "document_registered",
        entity_type="document",
        entity_id=document.id,
        details={"reason": security_result.reason} if not security_result.allowed else None,
    )
    if source_path:
        size_bytes, mtime_epoch = path_metadata(source)
        watched = upsert_watched_file(
            db,
            path=source_path,
            status="duplicate"
            if status == "duplicate"
            else ("quarantined" if status == "needs_review" else "registered"),
            size_bytes=size_bytes,
            mtime_epoch=mtime_epoch,
            document_id=document.id,
            job_id=job.id if job else None,
        )
        record_ingestion_event(
            db,
            event_type="duplicate"
            if status == "duplicate"
            else ("quarantined" if status == "needs_review" else "registered"),
            source_path=source_path,
            document_id=document.id,
            job_id=job.id if job else None,
            watched_file=watched,
        )
    db.commit()
    db.refresh(document)
    if job:
        db.refresh(job)
        if enqueue:
            from app.workers.routing import queue_for_document
            from app.workers.tasks import process_document_task

            cache_service.invalidate_search_cache()
            queue = queue_for_document(document, job.job_type)
            process_document_task.apply_async(args=(document.id, job.id), queue=queue)
            if source_path:
                watched = upsert_watched_file(
                    db,
                    path=source_path,
                    status="queued",
                    document_id=document.id,
                    job_id=job.id,
                )
                record_ingestion_event(
                    db,
                    event_type="queued",
                    source_path=source_path,
                    document_id=document.id,
                    job_id=job.id,
                    watched_file=watched,
                    details={"queue": queue},
                )
                db.commit()
    return document, job
