from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Document,
    DocumentBlock,
    DocumentChunk,
    DocumentEntity,
    DocumentPage,
    ExtractionJob,
    Plan,
)
from app.ocr.factory import get_ocr_engine_class
from app.parsers.router import parse_document
from app.services.business_extraction import persist_business_extraction
from app.services.cache import cache_service
from app.services.classification import classify_document
from app.services.ingestion_events import record_ingestion_event, upsert_watched_file
from app.services.metrics import track_document_failed, track_document_processed
from app.services.plan_extraction import persist_plan_extraction
from app.services.quality import evaluate_document_quality, update_document_quality
from app.services.tenant_access import apply_folder_rules_to_document
from app.services.webhooks import emit_integration_webhook
from app.workers.learning_tasks import _load_active_learned_rules

# How long the active-rules cache lives inside a single worker
# process. 60 s is a good trade-off: it absorbs batch backpressure
# (10+ docs/second peak) and stays well under the latency an
# operator expects between approving a rule and seeing it applied.
_LEARNED_RULES_CACHE_TTL = 60.0
_learned_rules_cache: dict[str, object] = {"expires_at": 0.0, "rules": []}


def _get_cached_learned_rules(db: Session) -> list:
    """Return the active learned rules, cached in-process for 60 s.

    Reloading on every document would add 1 extra query per
    processed document; under load that adds up. The cache is
    invalidated automatically by TTL and can be force-flushed by
    calling :func:`reset_learned_rules_cache` (e.g. from an admin
    endpoint right after approving a rule).
    """
    now = time.monotonic()
    cached = _learned_rules_cache.get("rules")
    expires_at = _learned_rules_cache.get("expires_at", 0.0)  # type: ignore[arg-type]
    if cached is not None and now < float(expires_at):  # type: ignore[arg-type]
        return list(cached)  # type: ignore[arg-type]
    try:
        rules = _load_active_learned_rules(db)
    except Exception:
        # If the rules table is missing or the query fails, fall
        # back to the no-rules path so classification still works.
        rules = []
    _learned_rules_cache["rules"] = list(rules)
    _learned_rules_cache["expires_at"] = now + _LEARNED_RULES_CACHE_TTL
    return list(rules)


def reset_learned_rules_cache() -> None:
    """Force the next classification call to reload the rules.

    Useful for tests and for the admin endpoint that approves a new
    rule and wants it applied to the very next document.
    """
    _learned_rules_cache["rules"] = []
    _learned_rules_cache["expires_at"] = 0.0


# This module sits at the centre of the document processing
# pipeline. It used to import many of its helpers from
# ``app.services.document_service`` (a re-export hub) via a
# ``_facade()`` helper that looked the module up through
# ``sys.modules`` at call time. The pattern worked but it was
# three problems at once: type checkers could not see the
# imports, a typo in the path would not surface until a webhook
# fired at 3am, and the indirection made the file hard to read.
# The hub itself (document_service.py) is preserved as a
# public facade for the routes and the worker, but this file
# now imports the helpers directly. There is no cycle:
# ``app.services.webhooks``, ``app.ocr.factory`` and
# ``app.parsers.router`` are all leaves that do not import
# anything from this module or from ``document_service``.

# ruff: noqa: E402  (intentional — the original module used
# a deferred import to break the import cycle with
# ``document_service``; the helper that lives here is only
# used during document processing, so the import is safe to
# resolve at the top of the module).
from app.services.document_embedding_pipeline import _replace_document_chunks


def sanitize_text_for_database(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("\x00", "")


def processing_mode_from_job_type(job_type: str | None) -> str:
    raw = (job_type or "").strip().lower()
    if not raw or raw in {"extract", "reprocess"}:
        return "full"
    if raw.startswith("reprocess:ocr_page:"):
        return "ocr_page"
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


def reprocess_page_number_from_job_type(job_type: str | None) -> int:
    raw = (job_type or "").strip().lower()
    prefix = "reprocess:ocr_page:"
    if not raw.startswith(prefix):
        raise ValueError("OCR page reprocess job is missing page number")
    try:
        page_number = int(raw.removeprefix(prefix))
    except ValueError as exc:
        raise ValueError("OCR page reprocess job has invalid page number") from exc
    if page_number < 1:
        raise ValueError("OCR page reprocess job has invalid page number")
    return page_number


def mode_requires_file_parse(mode_or_job_type: str | None) -> bool:
    return processing_mode_from_job_type(mode_or_job_type) in {"full", "ocr"}


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


def _relative_to_files(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(settings.files_dir.resolve()))
    except Exception:
        return path


def _resolve_files_dir_path(stored_path: str) -> Path:
    root = settings.files_dir.resolve()
    candidate = Path(stored_path)
    path = candidate.resolve() if candidate.is_absolute() else (root / stored_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Stored page image is outside files directory") from exc
    if path.is_symlink() or not path.is_file():
        raise ValueError("Stored page image not found")
    return path


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


def process_document(
    db: Session, *, document_id: int, job_id: int, final_failure: bool = True
) -> None:
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
        watched = upsert_watched_file(
            db,
            path=document.source_path,
            status="processing",
            document_id=document.id,
            job_id=job.id,
        )
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
            document.status = (
                previous_status if previous_status in {"processed", "needs_review"} else "processed"
            )
        elif mode == "ocr_page":
            needs_review = _process_ocr_page_only(
                db, document, page_number=reprocess_page_number_from_job_type(job.job_type)
            )
            document.status = "needs_review" if needs_review else "processed"
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
        track_document_processed()
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
        _handle_process_failure(
            db, document_id=document_id, job_id=job_id, error=exc, final_failure=final_failure
        )
        raise


def _handle_process_failure(
    db: Session,
    *,
    document_id: int,
    job_id: int,
    error: Exception,
    final_failure: bool,
) -> tuple[Document | None, ExtractionJob | None]:
    db.rollback()
    job = db.get(ExtractionJob, job_id)
    document = db.get(Document, document_id)
    if job:
        job.finished_at = datetime.utcnow() if final_failure else None
        job.error_message = str(error)
        job.status = "failed" if final_failure else "retrying"
    if document:
        document.error_message = str(error)
        if final_failure:
            document.status = "failed"
            document.quality_status = "failed"
            document.quality_score = 0.0
            document.quality_flags_json = ["processing_failed"]
            if document.source_path:
                watched = upsert_watched_file(
                    db,
                    path=document.source_path,
                    status="failed",
                    document_id=document.id,
                    job_id=job.id if job else None,
                    error_message=str(error),
                )
                record_ingestion_event(
                    db,
                    event_type="failed",
                    source_path=document.source_path,
                    document_id=document.id,
                    job_id=job.id if job else None,
                    watched_file=watched,
                    error_message=str(error),
                )
        else:
            document.status = "processing"
    db.commit()
    if final_failure and document and job:
        track_document_failed()
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
    return document, job


def _process_full_parse(db: Session, document: Document) -> bool:
    if not document.stored_filename:
        raise ValueError("Document has no stored file")
    stored_path = settings.files_dir / document.stored_filename
    page_image_dir = settings.files_dir / document.file_hash[:2] / f"{document.file_hash}_pages"
    ocr_engine = get_ocr_engine_class()()
    # OCR-FLOW — wire the cascade attempt recorder so the cascade
    # logs every tier tried per page. The recorder is set on the
    # engine via setattr because ``BaseOCREngine`` is a Protocol
    # and the ``CascadingOCREngine``-specific ``attempt_recorder``
    # is not in the contract; non-cascading engines (single
    # Tesseract, single PaddleOCR) simply ignore the attribute.
    _attach_cascade_recorder(ocr_engine, db, document.id)
    extracted = parse_document(stored_path, page_image_dir, ocr_engine)
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
            ocr_engine=extracted_page.ocr_engine,
            # Stamp the configured engine version so the periodic
            # re-OCR sweep can find pages produced with a stale
            # version. Pages with no engine (e.g. pymupdf-native text)
            # get the same label so they participate in the sweep
            # too — when an operator bumps the OCR stack, every page
            # should be re-evaluated.
            ocr_engine_version=settings.current_ocr_engine_version,
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
    needs_review = _apply_classification_and_extraction(
        db,
        document,
        text=extracted.text,
        page_count=len(extracted.pages),
        low_ocr_confidences=[
            page.ocr_confidence
            for page in extracted.pages
            if page.ocr_confidence is not None and page.ocr_confidence < 0.70
        ],
        pages=extracted.pages,
    )
    _replace_document_chunks(
        db,
        document.id,
        page_texts_list,
        document_type=document.document_type,
        original_filename=document.original_filename,
    )
    return needs_review


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
    _replace_document_chunks(
        db,
        document.id,
        page_texts,
        document_type=document.document_type,
        original_filename=document.original_filename,
    )


def _process_ocr_page_only(db: Session, document: Document, *, page_number: int) -> bool:
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .where(DocumentPage.page_number == page_number)
        .limit(1)
    )
    if not page:
        raise ValueError(f"Document page not found: {page_number}")
    if not page.image_path:
        page.page_status = "failed"
        page.error_message = (
            "Page has no image preview for OCR reprocess; run a full OCR reprocess first"
        )
        page.attempts = (page.attempts or 0) + 1
        db.flush()
        return _process_classification_only(db, document)

    started = time.perf_counter()
    page.page_status = "processing"
    page.error_message = None
    page.attempts = (page.attempts or 0) + 1
    db.flush()
    try:
        page_path = _resolve_files_dir_path(page.image_path)
        engine = get_ocr_engine_class()()
        ocr = engine.extract(page_path)
    except Exception as exc:
        page.page_status = "failed"
        page.error_message = str(exc)
        page.processing_time_ms = int((time.perf_counter() - started) * 1000)
        db.flush()
        return _process_classification_only(db, document)

    actual_engine = ocr.engine or engine.name
    page.text = sanitize_text_for_database(ocr.text)
    page.ocr_confidence = ocr.confidence
    page.page_status = _page_status_from_confidence(ocr.confidence)
    page.processing_time_ms = int((time.perf_counter() - started) * 1000)
    page.review_status = "pending"
    page.review_notes = None
    page.reviewed_at = None
    page.reviewed_by_id = None

    db.execute(
        delete(DocumentBlock)
        .where(DocumentBlock.document_id == document.id)
        .where(DocumentBlock.page_number == page_number)
    )
    db.flush()
    for block_payload in ocr.blocks:
        bbox = block_payload.bbox or (None, None, None, None)
        db.add(
            DocumentBlock(
                document_id=document.id,
                page_id=page.id,
                page_number=page.page_number,
                block_type="text",
                text=sanitize_text_for_database(block_payload.text),
                bbox_x1=bbox[0],
                bbox_y1=bbox[1],
                bbox_x2=bbox[2],
                bbox_y2=bbox[3],
                confidence=block_payload.confidence,
                source_engine=actual_engine,
            )
        )
    db.flush()
    page_texts = _load_existing_page_texts(db, document.id)
    needs_review = _apply_classification_and_extraction(
        db,
        document,
        text=_full_text_from_page_texts(page_texts),
        page_count=len(page_texts),
        low_ocr_confidences=_load_low_ocr_confidences(db, document.id),
    )
    _replace_document_chunks(
        db,
        document.id,
        page_texts,
        document_type=document.document_type,
        original_filename=document.original_filename,
    )
    return needs_review


def _apply_classification_and_extraction(
    db: Session,
    document: Document,
    *,
    text: str,
    page_count: int,
    low_ocr_confidences: list[float],
    pages: list | None = None,
) -> bool:
    # R1 — apply operator-approved learned rules so a pattern like
    # ``cliente_x → pedido`` overrides the generic filename/folder
    # heuristics. The rules are loaded once per worker process and
    # cached for ``_LEARNED_RULES_CACHE_TTL`` seconds so the cost is
    # amortised across all documents processed in the same batch.
    learned_rules = _get_cached_learned_rules(db)
    classification = classify_document(
        document.original_filename,
        document.source_path,
        text,
        learned_rules=learned_rules,
    )
    document.document_type = classification.document_type
    document.confidence = classification.confidence
    document.page_count = page_count

    business_result = persist_business_extraction(db, document, text, pages=pages)
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


# --------------------------------------------------------------------- #
# OCR-FLOW: cascade attempt recorder                                    #
# --------------------------------------------------------------------- #


def _attach_cascade_recorder(ocr_engine, db: Session, document_id: int) -> None:
    """Wire the cascade attempt recorder onto the OCR engine.

    The cascade logs every tier tried per page (OcrCascadeAttempt)
    so the admin UI can show the full Tesseract->Paddle->PP-Structure
    trace. We resolve page_id at log-time via a small SQL lookup
    because the cascade fires **before** the DocumentPage row is
    created by ``_process_full_parse``.

    Failures are swallowed: a missing or broken recorder must never
    break OCR.
    """
    from app.models.document import DocumentPage
    from app.models.ocr_cascade import OcrCascadeAttempt
    from sqlalchemy import select

    def _record(row: dict) -> None:
        try:
            document_id_inner = row.get("document_id")
            page_number = row.get("page_number")
            if not document_id_inner or page_number is None:
                return
            page = db.scalars(
                select(DocumentPage).where(
                    DocumentPage.document_id == document_id_inner,
                    DocumentPage.page_number == page_number,
                )
            ).first()
            if page is None:
                # Page not yet persisted; we cannot satisfy the FK.
                # Skip this attempt silently - the page row is created
                # in the loop that runs after parse_document and
                # subsequent re-OCR sweeps can backfill.
                return
            db.add(
                OcrCascadeAttempt(
                    document_id=document_id_inner,
                    page_id=page.id,
                    page_number=page_number,
                    tier=row["tier"],
                    tier_index=row["tier_index"],
                    success=row["success"],
                    duration_ms=row["duration_ms"],
                    confidence=row.get("confidence"),
                    chars=row["chars"],
                    reason=row.get("reason"),
                    error_message=row.get("error_message"),
                )
            )
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            # Logging only - never let a recorder failure break OCR.
            import logging as _logging

            _logging.getLogger(__name__).exception(
                "cascade attempt recorder failed"
            )

    try:
        setattr(ocr_engine, "current_document_id", document_id)
        setattr(ocr_engine, "attempt_recorder", _record)
    except Exception:
        pass
            # Logging only � never let a recorder failure break OCR.
            import logging as _logging
            _logging.getLogger(__name__).exception(
                \"cascade attempt recorder failed\"
            )

    try:
        setattr(ocr_engine, \"current_document_id\", document_id)
        setattr(ocr_engine, \"attempt_recorder\", _record)
    except Exception:
        pass
