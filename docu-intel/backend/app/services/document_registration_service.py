from __future__ import annotations

import logging
import mimetypes
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, ExtractionJob, User
from app.models.project import DocumentBudgetLink, DocumentOccurrence
from app.services.audit import write_audit
from app.services.budget_scope import (
    assign_document_budget_scope,
    get_or_create_budget_scope,
    get_or_create_project_for_budget,
)
from app.services.cache import cache_service
from app.services.file_security import inspect_file_for_ingestion
from app.services.file_storage import calculate_sha256, copy_to_storage
from app.services.ingestion_events import path_metadata, record_ingestion_event, upsert_watched_file
from app.services.project_path_resolver import classify_category, resolve_corpus_path
from app.services.tenant_access import apply_folder_rules_to_document

logger = logging.getLogger(__name__)

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
                # Phase 4: create DocumentOccurrence for the new path
                _create_occurrence(db, existing, source, source_path)
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
    apply_folder_rules_to_document(db, document)
    # Phase 4: create DocumentOccurrence for every registered document
    if source_path:
        occurrence = _create_occurrence(db, document, source, source_path)
        # Generic inbox paths have no hierarchy; retain the old standalone
        # scope only for those paths until they receive a manual assignment.
        if occurrence is None:
            assign_document_budget_scope(db, document)
    else:
        assign_document_budget_scope(db, document)
    db.flush()

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
    if enqueue and job:
        from app.workers.routing import queue_for_document
        from app.workers.tasks import process_document_task

        cache_service.invalidate_search_cache()
        # P1.1: probe PDFs to route to the right queue
        queue = queue_for_document(document, job.job_type)
        if extension == ".pdf" and source.exists():
            try:
                from app.services.document_probe import probe_pdf

                probe = probe_pdf(source)
                from app.workers.routing import queue_for_probe_result

                queue = queue_for_probe_result(probe.route.value)
                logger.info(
                    "PDF probe: document_id=%s route=%s reason=%s pages=%s",
                    document.id,
                    probe.route.value,
                    probe.reason,
                    probe.page_count,
                )
            except Exception as exc:
                logger.debug("PDF probe failed, using default routing: %s", exc)
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


def _create_occurrence(
    db: Session,
    document: Document,
    source: Path,
    source_path: str,
) -> DocumentOccurrence | None:
    """Create a DocumentOccurrence for a file path if one doesn't already exist.

    Phase 4: every file registration creates an occurrence linking the
    document to its source path, brand, hotel, budget, and category.
    """
    source_root = _occurrence_source_root(source_path)
    if source_root is None:
        # Arbitrary inbox paths remain standalone until assigned manually.
        # Hierarchical upload paths are handled separately below because their
        # ``upload/<namespace>/...`` prefix is a safe, explicit context.
        return None
    resolution = resolve_corpus_path(source_path, source_root)
    source_name = _logical_source_filename(document, source_path, source)
    category = classify_category(source_name, resolution.category)
    year = resolution.year or _default_occurrence_year(document, source_root)

    # Find or create brand
    from app.models.tenant import HotelChain

    brand = None
    if resolution.brand:
        brand = db.scalar(select(HotelChain).where(HotelChain.name == resolution.brand))
        if not brand:
            brand = HotelChain(name=resolution.brand)
            db.add(brand)
            db.flush()

    # Find or create hotel
    from app.models.tenant import Hotel

    hotel = None
    if resolution.hotel and brand:
        hotel = db.scalar(
            select(Hotel).where(
                Hotel.name == resolution.hotel,
                Hotel.chain_id == brand.id,
            )
        )
        if not hotel:
            hotel = Hotel(name=resolution.hotel, chain_id=brand.id)
            db.add(hotel)
            db.flush()

    # A path without a recognised brand is an inbox item, not a synthetic
    # project.  It remains available to the normal ingestion workflow until
    # a human assigns its hierarchy.
    if brand is None:
        return None

    folder_budget_code = resolution.budget_code
    document_budget_code = _document_budget_code(db, document.id)
    if folder_budget_code and document_budget_code:
        association_status = (
            "verified" if folder_budget_code == document_budget_code else "conflict"
        )
        resolved_budget_code = folder_budget_code if association_status == "verified" else None
    elif folder_budget_code:
        association_status = "folder_only"
        resolved_budget_code = folder_budget_code
    elif document_budget_code:
        association_status = "content_only"
        resolved_budget_code = document_budget_code
    else:
        association_status = "manual"
        resolved_budget_code = None

    evidence = {
        "source_path": source_path,
        "resolver": "folder",
        "folder_budget_code": folder_budget_code,
        "document_budget_code": document_budget_code,
    }

    # Contextual scope/project: the same code may legitimately exist in
    # multiple years, brands or hotels.  In a conflict the folder creates a
    # reviewable membership but never becomes a verified association.
    budget_scope = None
    project = None
    budget_code_for_context = resolved_budget_code or folder_budget_code
    if budget_code_for_context:
        budget_scope = get_or_create_budget_scope(
            db,
            year,
            brand.id,
            hotel.id if hotel else None,
            budget_code_for_context,
        )
        project = get_or_create_project_for_budget(
            db,
            year,
            brand.id,
            hotel.id if hotel else None,
            budget_scope.id,
        )
        # ``Document.budget_scope_id`` is retained solely as the legacy
        # primary link.  Membership is represented by the occurrence/link.
        document.budget_scope_id = budget_scope.id

    # Check if occurrence already exists for this exact path
    existing_occ = db.scalar(
        select(DocumentOccurrence).where(
            DocumentOccurrence.source_root == source_root,
            DocumentOccurrence.source_path == source_path,
        )
    )
    if existing_occ:
        # Same path with a new SHA is a new document version.  The historical
        # Document and its audit events remain intact; the live occurrence now
        # points to the latest physical version.
        existing_occ.document_id = document.id
        existing_occ.year = year
        existing_occ.brand_id = brand.id
        existing_occ.hotel_id = hotel.id if hotel else None
        existing_occ.budget_scope_id = budget_scope.id if budget_scope else None
        existing_occ.project_id = project.id if project else None
        existing_occ.category = category
        existing_occ.original_filename = source_name
        existing_occ.folder_budget_code = folder_budget_code
        existing_occ.document_budget_code = document_budget_code
        existing_occ.resolved_budget_code = resolved_budget_code
        existing_occ.association_status = association_status
        existing_occ.association_evidence = evidence
        existing_occ.last_seen_at = datetime.now(UTC)
        _ensure_document_budget_link(
            db,
            document=document,
            occurrence=existing_occ,
            budget_scope=budget_scope,
            status=association_status,
            extracted_code=budget_code_for_context,
            evidence=evidence,
        )
        return existing_occ

    occurrence = DocumentOccurrence(
        document_id=document.id,
        source_path=source_path,
        source_root=source_root,
        year=year,
        brand_id=brand.id,
        hotel_id=hotel.id if hotel else None,
        budget_scope_id=budget_scope.id if budget_scope else None,
        project_id=project.id if project else None,
        category=category,
        original_filename=source_name,
        folder_budget_code=folder_budget_code,
        document_budget_code=document_budget_code,
        resolved_budget_code=resolved_budget_code,
        association_status=association_status,
        association_evidence=evidence,
        is_primary=True,
    )
    db.add(occurrence)
    db.flush()
    _ensure_document_budget_link(
        db,
        document=document,
        occurrence=occurrence,
        budget_scope=budget_scope,
        status=association_status,
        extracted_code=budget_code_for_context,
        evidence=evidence,
    )
    return occurrence


def _is_path_within_root(source_path: str, source_root: str) -> bool:
    normalized_path = source_path.replace("\\", "/").rstrip("/")
    normalized_root = source_root.replace("\\", "/").rstrip("/")
    return normalized_path == normalized_root or normalized_path.startswith(f"{normalized_root}/")


def _occurrence_source_root(source_path: str) -> str | None:
    """Return the trusted identity root for corpus or hierarchical uploads.

    Upload membership is intentionally opt-in: only paths under ``upload/``
    with a recognisable folder hierarchy reach this resolver.  Other input
    directories retain the deny-by-default behaviour tested for the corpus.
    """
    normalized = source_path.replace("\\", "/").strip().strip("/")
    corpus_root = str(settings.source_corpus_dir).replace("\\", "/").rstrip("/")
    if _is_path_within_root(source_path, corpus_root):
        return corpus_root
    parts = [part for part in normalized.split("/") if part]
    if not parts or parts[0].lower() != "upload":
        return None
    if len(parts) >= 2 and parts[1].isdigit():
        return f"upload/{parts[1]}"
    return "upload"


def _default_occurrence_year(document: Document, source_root: str) -> int:
    """Derive a stable project year without the old hard-coded 2025 value."""
    for candidate in (source_root, str(settings.source_corpus_dir), document.source_path or ""):
        for segment in candidate.replace("\\", "/").split("/"):
            if re.fullmatch(r"\d{4}", segment):
                return int(segment)
    created_at = getattr(document, "created_at", None)
    if created_at is not None:
        return int(created_at.year)
    return datetime.now(UTC).year


def _logical_source_filename(document: Document, source_path: str, source: Path) -> str:
    """Use the logical upload name, never a temporary staging filename."""
    from_path = source_path.replace("\\", "/").rstrip("/").split("/")[-1]
    if from_path:
        return from_path
    from_document = (document.original_filename or "").replace("\\", "/").split("/")[-1]
    return from_document or source.name


def _document_budget_code(db: Session, document_id: int) -> str | None:
    """Return the extracted budget evidence, if processing has produced it."""
    from app.models import DocumentEntity

    return db.scalar(
        select(DocumentEntity.entity_value)
        .where(DocumentEntity.document_id == document_id)
        .where(DocumentEntity.entity_type == "budget_number")
        .order_by(DocumentEntity.confidence.desc(), DocumentEntity.id.asc())
        .limit(1)
    )


def _ensure_document_budget_link(
    db: Session,
    *,
    document: Document,
    occurrence: DocumentOccurrence,
    budget_scope,
    status: str,
    extracted_code: str | None,
    evidence: dict[str, str | None],
) -> None:
    if budget_scope is None:
        return
    link = db.scalar(
        select(DocumentBudgetLink).where(
            DocumentBudgetLink.document_id == document.id,
            DocumentBudgetLink.budget_scope_id == budget_scope.id,
        )
    )
    if link is None:
        db.add(
            DocumentBudgetLink(
                document_id=document.id,
                occurrence_id=occurrence.id,
                budget_scope_id=budget_scope.id,
                source="folder" if evidence["folder_budget_code"] else "content",
                extracted_code=extracted_code,
                confidence=1.0 if status == "verified" else 0.75,
                status=status,
                evidence_json=evidence,
            )
        )
        return
    link.occurrence_id = occurrence.id
    link.status = status
    link.extracted_code = extracted_code
    link.evidence_json = evidence
