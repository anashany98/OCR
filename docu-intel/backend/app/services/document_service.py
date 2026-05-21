from __future__ import annotations

import mimetypes
import tempfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, DocumentBlock, DocumentChunk, DocumentEntity, DocumentPage, ExtractionJob, Plan, User
from app.ocr.paddle import PaddleOCREngine
from app.parsers.router import parse_document
from app.services.audit import write_audit
from app.services.budget_scope import assign_document_budget_scope
from app.services.business_extraction import persist_business_extraction
from app.services.cache import cache_service
from app.services.chunking import build_chunks
from app.services.classification import classify_document
from app.services.embeddings import embed_many, should_create_embeddings
from app.services.file_storage import calculate_sha256, copy_to_storage
from app.services.file_security import inspect_file_for_ingestion
from app.services.ingestion_events import path_metadata, record_ingestion_event, upsert_watched_file
from app.services.plan_extraction import persist_plan_extraction
from app.services.quality import evaluate_document_quality, update_document_quality
from app.services.tenant_access import apply_folder_rules_to_document
from app.services.webhooks import emit_integration_webhook


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
    from app.services.runtime_settings import get_max_upload_size_mb
    max_upload_size_mb = get_max_upload_size_mb()
    max_bytes = max(0, int(max_upload_size_mb) * 1024 * 1024)
    bytes_written = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        temp_path = Path(tmp.name)
    try:
        stream.seek(0, 2)
        total_size = stream.tell()
        stream.seek(0)
        if total_size > max_bytes:
            raise ValueError(f"max_upload_size exceeded: {max_upload_size_mb} MB")
        with temp_path.open("wb") as tmp:
            while chunk := stream.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ValueError(f"max_upload_size exceeded: {max_upload_size_mb} MB")
                tmp.write(chunk)
        if temp_path.stat().st_size == 0 and total_size > 0:
            raise IOError("File write produced empty file")
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
        .where(Document.status != "duplicate")
        .where(Document.deleted_at.is_(None))
        .order_by(Document.id.asc())
    )

    stored_filename: str | None = None
    status = "pending"
    duplicate_of_document_id: int | None = None
    if existing:
        # If existing document is fully processed, return it directly (skip OCR)
        if existing.status in {"processed", "needs_review"}:
            return existing, None
        # Otherwise mark as duplicate
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
        quality_status="needs_human_review" if status == "needs_review" else ("duplicate" if status == "duplicate" else "pending"),
        quality_score=0.0 if status == "needs_review" else None,
        quality_flags_json=[f"security:{security_result.reason}"] if not security_result.allowed else [],
        error_message=f"File quarantined: {security_result.reason}" if not security_result.allowed else None,
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
            status="duplicate" if status == "duplicate" else ("quarantined" if status == "needs_review" else "registered"),
            size_bytes=size_bytes,
            mtime_epoch=mtime_epoch,
            document_id=document.id,
            job_id=job.id if job else None,
        )
        record_ingestion_event(
            db,
            event_type="duplicate" if status == "duplicate" else ("quarantined" if status == "needs_review" else "registered"),
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
            from app.workers.tasks import process_document_task
            from app.workers.routing import queue_for_document

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
        document.processed_at = None
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


def soft_delete_document(db: Session, *, document: Document, user: User) -> Document:
    document.deleted_at = datetime.utcnow()
    document.deleted_by_id = user.id
    write_audit(db, user=user, action="document_deleted_logically", entity_type="document", entity_id=document.id)
    cache_service.invalidate_search_cache()
    db.commit()
    db.refresh(document)
    return document


def process_document(db: Session, *, document_id: int, job_id: int) -> None:
    document = db.get(Document, document_id)
    job = db.get(ExtractionJob, job_id)
    if not document or not job:
        return

    mode = processing_mode_from_job_type(job.job_type)
    previous_status = document.status
    apply_folder_rules_to_document(db, document)
    job.status = "processing"
    job.started_at = datetime.utcnow()
    job.error_message = None
    document.status = "processing"
    document.error_message = None
    db.commit()
    if document.source_path:
        watched = upsert_watched_file(db, path=document.source_path, status="processing", document_id=document.id, job_id=job.id)
        record_ingestion_event(
            db,
            event_type="processing",
            source_path=document.source_path,
            document_id=document.id,
            job_id=job.id,
            watched_file=watched,
        )
        db.commit()

    try:
        if mode == "embeddings":
            _process_embeddings_only(db, document)
            document.status = previous_status if previous_status in {"processed", "needs_review"} else "processed"
        elif mode == "classification":
            needs_review = _process_classification_only(db, document)
            document.status = "needs_review" if needs_review else "processed"
        else:
            needs_review = _process_full_parse(db, document)
            document.status = "needs_review" if needs_review else "processed"

        document.processed_at = datetime.utcnow()
        job.status = "processed"
        job.finished_at = datetime.utcnow()
        job.error_message = None
        cache_service.invalidate_search_cache()
        if document.source_path:
            watched = upsert_watched_file(
                db,
                path=document.source_path,
                status=document.status,
                document_id=document.id,
                job_id=job.id,
            )
            record_ingestion_event(
                db,
                event_type=document.status,
                source_path=document.source_path,
                document_id=document.id,
                job_id=job.id,
                watched_file=watched,
            )
        db.commit()
        _emit_document_webhooks(document, job)
    except Exception as exc:
        db.rollback()
        job = db.get(ExtractionJob, job_id)
        document = db.get(Document, document_id)
        if job:
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = str(exc)
        if document:
            document.status = "failed"
            document.quality_status = "failed"
            document.quality_score = 0.0
            document.quality_flags_json = ["processing_failed"]
            document.error_message = str(exc)
            if document.source_path:
                watched = upsert_watched_file(
                    db,
                    path=document.source_path,
                    status="failed",
                    document_id=document.id,
                    job_id=job.id if job else None,
                    error_message=str(exc),
                )
                record_ingestion_event(
                    db,
                    event_type="failed",
                    source_path=document.source_path,
                    document_id=document.id,
                    job_id=job.id if job else None,
                    watched_file=watched,
                    error_message=str(exc),
                )
        db.commit()
        if document and job:
            emit_integration_webhook(
                "document.failed",
                {
                    "document_id": document.id,
                    "job_id": job.id,
                    "filename": document.original_filename,
                    "status": document.status,
                    "error_message": document.error_message,
                },
            )
        raise


def processing_mode_from_job_type(job_type: str | None) -> str:
    raw = (job_type or "").strip().lower()
    if not raw or raw in {"extract", "reprocess"}:
        return "full"
    candidate = raw.split(":", 1)[1] if ":" in raw else raw
    aliases = {
        "text": "ocr",
        "entities": "classification",
        "chunks": "embeddings",
    }
    candidate = aliases.get(candidate, candidate)
    if candidate in {"full", "ocr", "classification", "embeddings"}:
        return candidate
    return "full"


def mode_requires_file_parse(mode_or_job_type: str | None) -> bool:
    return processing_mode_from_job_type(mode_or_job_type) in {"full", "ocr"}


def prepare_document_chunks(document_id: int, page_texts: list[tuple[int, str | None]]) -> list[DocumentChunk]:
    chunk_payloads: list[tuple[int, str, int]] = []
    for page_number, page_text in page_texts:
        clean_text = sanitize_text_for_database(page_text)
        for chunk_text, token_count in build_chunks(clean_text):
            chunk_payloads.append((page_number, chunk_text, token_count))

    embedding_payloads = (
        embed_many_with_metadata([chunk_text for _, chunk_text, _ in chunk_payloads])
        if chunk_payloads and should_create_embeddings()
        else [(None, None, False)] * len(chunk_payloads)
    )
    if len(embedding_payloads) != len(chunk_payloads):
        raise ValueError("Embedding count does not match chunk count")

    return [
        DocumentChunk(
            document_id=document_id,
            page_number=page_number,
            chunk_text=chunk_text,
            embedding=embedding,
            embedding_provider_used=provider,
            embedding_fallback=fallback,
            needs_reembedding=fallback,
            token_count=token_count,
        )
        for (page_number, chunk_text, token_count), (embedding, provider, fallback) in zip(chunk_payloads, embedding_payloads, strict=True)
    ]


def embed_many_with_metadata(texts: list[str]) -> list[tuple[list[float], str, bool]]:
    embeddings = embed_many(texts)
    provider = settings.embedding_provider.lower().strip() or "local_hash"
    fallback = provider in {"local", "local_hash"}
    return [(embedding, provider, fallback) for embedding in embeddings]


def _process_full_parse(db: Session, document: Document) -> bool:
    if not document.stored_filename:
        raise ValueError("Document has no stored file")
    stored_path = settings.files_dir / document.stored_filename
    page_image_dir = settings.files_dir / document.file_hash[:2] / f"{document.file_hash}_pages"
    extracted = parse_document(stored_path, page_image_dir, PaddleOCREngine())
    for extracted_page in extracted.pages:
        extracted_page.text = sanitize_text_for_database(extracted_page.text)
        for extracted_block in extracted_page.blocks:
            extracted_block.text = sanitize_text_for_database(extracted_block.text)

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    db.execute(delete(DocumentBlock).where(DocumentBlock.document_id == document.id))
    db.execute(delete(DocumentEntity).where(DocumentEntity.document_id == document.id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    db.execute(delete(Plan).where(Plan.document_id == document.id))
    db.flush()

    for extracted_page in extracted.pages:
        page = DocumentPage(
            document_id=document.id,
            page_number=extracted_page.page_number,
            width=extracted_page.width,
            height=extracted_page.height,
            text=extracted_page.text,
            image_path=_relative_to_files(extracted_page.image_path),
            page_status=_page_status_from_confidence(extracted_page.ocr_confidence),
            ocr_confidence=extracted_page.ocr_confidence,
            attempts=1 if extracted_page.ocr_confidence is not None else 0,
        )
        db.add(page)
        db.flush()
        for extracted_block in extracted_page.blocks:
            bbox = extracted_block.bbox or (None, None, None, None)
            block = DocumentBlock(
                document_id=document.id,
                page_id=page.id,
                page_number=extracted_block.page_number,
                block_type=extracted_block.block_type,
                text=extracted_block.text,
                bbox_x1=bbox[0],
                bbox_y1=bbox[1],
                bbox_x2=bbox[2],
                bbox_y2=bbox[3],
                confidence=extracted_block.confidence,
                source_engine=extracted_block.source_engine,
            )
            db.add(block)

    page_texts_list = [(page.page_number, page.text) for page in extracted.pages]
    _replace_document_chunks(db, document.id, page_texts_list)
    return _apply_classification_and_extraction(
        db,
        document,
        text=extracted.text,
        page_count=len(extracted.pages),
        low_ocr_confidences=[
            page.ocr_confidence
            for page in extracted.pages
            if page.ocr_confidence is not None and page.ocr_confidence < 0.70
        ],
    )


def _process_classification_only(db: Session, document: Document) -> bool:
    page_texts = _load_existing_page_texts(db, document.id)
    if not page_texts:
        raise ValueError("No extracted pages available; run a full or OCR reprocess first")
    return _apply_classification_and_extraction(
        db,
        document,
        text=_full_text_from_page_texts(page_texts),
        page_count=len(page_texts),
        low_ocr_confidences=_load_low_ocr_confidences(db, document.id),
    )


def _process_embeddings_only(db: Session, document: Document) -> None:
    page_texts = _load_existing_page_texts(db, document.id)
    if not page_texts:
        raise ValueError("No extracted pages available; run a full or OCR reprocess first")
    _replace_document_chunks(db, document.id, page_texts)


def _apply_classification_and_extraction(
    db: Session,
    document: Document,
    *,
    text: str,
    page_count: int,
    low_ocr_confidences: list[float],
) -> bool:
    classification = classify_document(document.original_filename, document.source_path, text)
    document.document_type = classification.document_type
    document.confidence = classification.confidence
    document.page_count = page_count

    business_result = persist_business_extraction(db, document, text)
    db.execute(delete(Plan).where(Plan.document_id == document.id))
    db.flush()
    plan_result = persist_plan_extraction(db, document, text)

    quality = evaluate_document_quality(
        db,
        document,
        text=text,
        page_count=page_count,
        low_ocr_confidences=low_ocr_confidences,
        business_needs_review=business_result.needs_review,
        plan_needs_review=plan_result.needs_review,
    )
    update_document_quality(db, document, quality)
    return quality.needs_review


def _replace_document_chunks(db: Session, document_id: int, page_texts: list[tuple[int, str | None]]) -> None:
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    for chunk in prepare_document_chunks(document_id, page_texts):
        db.add(chunk)
    db.flush()


def _page_status_from_confidence(ocr_confidence: float | None) -> str:
    if ocr_confidence is None:
        return "processed"
    if ocr_confidence < 0.70:
        return "processed_low_confidence"
    return "processed"


def _load_existing_page_texts(db: Session, document_id: int) -> list[tuple[int, str | None]]:
    rows = db.execute(
        select(DocumentPage.page_number, DocumentPage.text)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc())
    ).all()
    return [(int(page_number), sanitize_text_for_database(text)) for page_number, text in rows]


def _load_low_ocr_confidences(db: Session, document_id: int) -> list[float]:
    return list(
        db.scalars(
            select(DocumentPage.ocr_confidence)
            .join(Document, Document.id == DocumentPage.document_id)
            .where(DocumentPage.document_id == document_id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentPage.ocr_confidence.is_not(None))
            .where(DocumentPage.ocr_confidence < 0.70)
        ).all()
    )


def _full_text_from_page_texts(page_texts: list[tuple[int, str | None]]) -> str:
    return "\n\n".join(text for _, text in page_texts if text)


def sanitize_text_for_database(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("\x00", "")


def _relative_to_files(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(settings.files_dir.resolve()))
    except Exception:
        return path


def _type_from_extension(extension: str) -> str:
    if extension in {".xls", ".xlsx", ".xlsm", ".csv", ".tsv"}:
        return "excel"
    if extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return "imagen"
    return "desconocido"


def _emit_document_webhooks(document: Document, job: ExtractionJob) -> None:
    payload = {
        "document_id": document.id,
        "job_id": job.id,
        "filename": document.original_filename,
        "document_type": document.document_type,
        "status": document.status,
        "confidence": document.confidence,
        "processed_at": document.processed_at.isoformat() if document.processed_at else None,
    }
    if document.status == "needs_review":
        emit_integration_webhook("document.needs_review", payload)
    elif document.status == "processed":
        emit_integration_webhook("document.processed", payload)
    emit_integration_webhook("job.finished", payload)
