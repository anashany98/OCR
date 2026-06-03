from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Document, DocumentPage, ExtractionJob, User
from app.services.audit import write_audit
from app.services.cache import cache_service
from app.services.document_processing_core import processing_mode_from_job_type


def reprocess_document(
    db: Session,
    *,
    document: Document,
    user: User | None = None,
    enqueue: bool = True,
    job_type: str = "reprocess",
) -> ExtractionJob:
    mode = processing_mode_from_job_type(job_type)
    if mode != "embeddings":
        document.status = "pending"
        document.quality_status = "pending"
        document.quality_flags_json = []
    document.error_message = None
    job = ExtractionJob(document_id=document.id, job_type=job_type, status="pending")
    db.add(job)
    write_audit(db, user=user, action="document_reprocess_requested", entity_type="document", entity_id=document.id)
    db.commit()
    db.refresh(job)
    if enqueue:
        from app.workers.tasks import process_document_task
        from app.workers.routing import queue_for_document

        cache_service.invalidate_search_cache()
        process_document_task.apply_async(args=(document.id, job.id), queue=queue_for_document(document, job.job_type))
    return job


def reprocess_document_page(
    db: Session,
    *,
    page: DocumentPage,
    user: User | None = None,
    enqueue: bool = True,
) -> ExtractionJob:
    document = db.get(Document, page.document_id)
    if not document:
        raise ValueError("Document page has no document")
    page.page_status = "queued"
    page.error_message = None
    page.review_status = "pending"
    page.review_notes = None
    page.reviewed_at = None
    page.reviewed_by_id = None
    document.status = "pending"
    document.quality_status = "pending"
    document.quality_flags_json = []
    document.error_message = None
    job = ExtractionJob(document_id=document.id, job_type=f"reprocess:ocr_page:{page.page_number}", status="pending")
    db.add(job)
    write_audit(
        db,
        user=user,
        action="document_page_reprocess_requested",
        entity_type="document_page",
        entity_id=page.id,
        details={"document_id": document.id, "page_number": page.page_number},
    )
    db.commit()
    db.refresh(job)
    if enqueue:
        from app.workers.tasks import process_document_task
        from app.workers.routing import queue_for_document

        cache_service.invalidate_search_cache()
        process_document_task.apply_async(args=(document.id, job.id), queue=queue_for_document(document, job.job_type))
    return job


def soft_delete_document(db: Session, *, document: Document, user: User) -> Document:
    document.deleted_at = datetime.utcnow()
    document.deleted_by_id = user.id
    write_audit(db, user=user, action="document_deleted_logically", entity_type="document", entity_id=document.id)
    cache_service.invalidate_search_cache()
    db.commit()
    db.refresh(document)
    return document
