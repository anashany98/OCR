from datetime import datetime
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentPage,
    IngestionEvent,
    WatchedFile,
)
from app.schemas.admin import (
    OcrReviewPageRead,
    ProductionChecklistItem,
)


def _get_or_404(db: Session, model, item_id: int, message: str):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(status_code=404, detail=message)
    return item


def count_where(db: Session, *criteria) -> int:
    stmt = select(func.count()).select_from(Document).where(Document.deleted_at.is_(None), *criteria)
    return int(db.scalar(stmt) or 0)


def _watched_file_payload(row: WatchedFile) -> dict:
    return {
        "id": row.id,
        "path": row.path,
        "status": row.status,
        "size_bytes": row.size_bytes,
        "mtime_epoch": row.mtime_epoch,
        "document_id": row.document_id,
        "job_id": row.job_id,
        "error_message": row.error_message,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "updated_at": row.updated_at,
    }


def _document_operation_payload(document: Document) -> dict:
    return {
        "id": document.id,
        "original_filename": document.original_filename,
        "source_path": document.source_path,
        "file_size": document.file_size,
        "document_type": document.document_type,
        "status": document.status,
        "quality_status": document.quality_status,
        "quality_score": document.quality_score,
        "confidence": document.confidence,
        "page_count": document.page_count,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "processed_at": document.processed_at.isoformat() if document.processed_at else None,
    }


def _ocr_review_payload(page: DocumentPage, document: Document) -> OcrReviewPageRead:
    text = page.text or ""
    blocks = list(
        db_blocks
        for db_blocks in page.blocks
    )
    return OcrReviewPageRead(
        document_id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        status=document.status,
        confidence=document.confidence,
        page_id=page.id,
        page_number=page.page_number,
        ocr_confidence=page.ocr_confidence,
        review_status=page.review_status,
        review_notes=page.review_notes,
        reviewed_at=page.reviewed_at,
        reviewed_by_id=page.reviewed_by_id,
        quality_status=document.quality_status,
        quality_score=document.quality_score,
        quality_flags_json=document.quality_flags_json or [],
        text=text,
        text_excerpt=text[:800],
        blocks=[
            {
                "id": block.id,
                "block_type": block.block_type,
                "text": block.text,
                "bbox_x1": block.bbox_x1,
                "bbox_y1": block.bbox_y1,
                "bbox_x2": block.bbox_x2,
                "bbox_y2": block.bbox_y2,
                "confidence": block.confidence,
                "source_engine": block.source_engine,
            }
            for block in sorted(blocks, key=lambda item: item.id)
        ],
        preview_url=f"/documents/{document.id}/pages/{page.page_number}/image" if page.image_path else None,
        created_at=page.created_at,
    )


def _checklist_item(key: str, title: str, check: dict, ok_description: str, action_url: str) -> ProductionChecklistItem:
    status = str(check.get("status", "warning"))
    normalized_status = status if status in {"ok", "warning", "error"} else "warning"
    detail = check.get("detail")
    description = ok_description if normalized_status == "ok" and not detail else str(detail or ok_description)
    return ProductionChecklistItem(
        key=key,
        title=title,
        status=normalized_status,
        description=description,
        action_url=action_url,
    )


def _normalize_preview_path(value: str) -> str:
    import re
    clean = value.replace("\\", "/").strip().lower()
    clean = re.sub(r"/+", "/", clean)
    return clean


def _ingestion_event_payload(row: IngestionEvent) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "source_path": row.source_path,
        "document_id": row.document_id,
        "job_id": row.job_id,
        "watched_file_id": row.watched_file_id,
        "details_json": row.details_json,
        "error_message": row.error_message,
        "created_at": row.created_at,
    }


def _normalized_tags(values) -> list[str]:
    if not values:
        return []
    return sorted({str(value).strip().lower() for value in values if str(value).strip()})


def _severity_rank(severity: str) -> int:
    return {"info": 1, "warning": 2, "error": 3}.get(severity, 0)


def _validate_hotel_assignment(db: Session, chain_id: int | None, hotel_id: int | None) -> None:
    from app.models import Hotel, HotelChain
    if chain_id:
        _get_or_404(db, HotelChain, chain_id, "Hotel chain not found")
    if hotel_id:
        hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
        if chain_id and hotel.chain_id != chain_id:
            raise HTTPException(status_code=400, detail="Hotel does not belong to selected chain")


def _new_api_key() -> str:
    import secrets
    return f"di_{secrets.token_urlsafe(32)}"


def _normalize_scopes(scopes: list[str]) -> list[str]:
    allowed = {"read", "upload", "admin"}
    normalized = sorted({scope.strip().lower() for scope in scopes if scope and scope.strip()})
    invalid = [scope for scope in normalized if scope not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid scopes: {', '.join(invalid)}")
    return normalized or ["read"]
