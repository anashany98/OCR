from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.routes.admin_helpers import _get_or_404, _ocr_review_payload
from app.core.config import settings
from app.database.session import get_db
from app.models import (
    Document,
    DocumentAccessMetadata,
    DocumentPage,
    ExtractionJob,
    OcrAttempt,
    User,
)
from app.schemas.admin import (
    JobActionResponse,
    OcrReviewPageRead,
    OcrReviewPageUpdate,
    QualityRecalculateRequest,
    QualityRecalculateResponse,
    QualityRulesRead,
    QualitySummaryRead,
)
from app.schemas.documents import DocumentRead
from app.services.audit import write_audit
from app.services.data_quality import quality_rules_payload, quality_summary, recalculate_quality
from app.services.document_service import reprocess_document_page
from app.services.ocr_page_roles import ocr_applicable_clause
from app.services.quality import refresh_quality_from_existing_pages

router = APIRouter(prefix="/admin")


@router.get("/ocr-automation-metrics")
def ocr_automation_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    """Small bounded operational summary for the automated OCR policy."""
    rows = db.execute(
        select(OcrAttempt.engine, OcrAttempt.decision, func.count(OcrAttempt.id))
        .group_by(OcrAttempt.engine, OcrAttempt.decision)
        .order_by(OcrAttempt.engine, OcrAttempt.decision)
    ).all()
    pending = int(
        db.scalar(
            select(func.count()).select_from(DocumentPage).where(
                DocumentPage.ocr_decision == "review_required",
                DocumentPage.review_status != "approved",
            )
        )
        or 0
    )
    return {
        "attempts": [
            {"engine": engine, "decision": decision or "unknown", "count": count}
            for engine, decision, count in rows
        ],
        "pending_review": pending,
    }


@router.get("/quality/rules", response_model=QualityRulesRead)
def quality_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return quality_rules_payload(db)


@router.get("/quality/summary", response_model=QualitySummaryRead)
def quality_summary_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return quality_summary(db)


@router.post("/quality/recalculate", response_model=QualityRecalculateResponse)
def quality_recalculate(
    payload: QualityRecalculateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> QualityRecalculateResponse:
    result = recalculate_quality(db, limit=payload.limit)
    write_audit(
        db,
        user=user,
        action="quality_recalculated",
        entity_type="document",
        details={
            "matched": result.matched,
            "updated": result.updated,
            "needs_review": result.needs_review,
        },
    )
    db.commit()
    return QualityRecalculateResponse(
        matched=result.matched, updated=result.updated, needs_review=result.needs_review
    )


@router.get("/ocr-review", response_model=list[OcrReviewPageRead])
@router.get("/quality/ocr-review", response_model=list[OcrReviewPageRead])
def ocr_review(
    max_confidence: float = Query(default=settings.low_ocr_confidence_threshold, ge=0, le=1),
    document_type: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[OcrReviewPageRead]:
    stmt = (
        select(DocumentPage, Document)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(ocr_applicable_clause(DocumentPage.ocr_content_kind))
        .where(
            or_(
                and_(
                    DocumentPage.ocr_confidence.is_not(None),
                    DocumentPage.ocr_confidence < max_confidence,
                ),
                DocumentPage.ocr_decision == "review_required",
            )
        )
        .order_by(DocumentPage.ocr_confidence.asc(), Document.created_at.desc())
    )
    if review_status:
        stmt = stmt.where(DocumentPage.review_status == review_status)
    else:
        stmt = stmt.where(DocumentPage.review_status != "approved")
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if status:
        stmt = stmt.where(Document.status == status)
    rows = db.execute(stmt.limit(limit)).all()
    return [_ocr_review_payload(page, document) for page, document in rows]


@router.patch("/ocr-review/{page_id}", response_model=OcrReviewPageRead)
@router.patch("/quality/pages/{page_id}/review", response_model=OcrReviewPageRead)
def update_ocr_review(
    page_id: int,
    payload: OcrReviewPageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> OcrReviewPageRead:
    page = db.get(DocumentPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="OCR review page not found")
    document = _get_or_404(db, Document, page.document_id, "Document not found")
    page.review_status = payload.review_status
    page.review_notes = payload.review_notes
    page.reviewed_at = datetime.now(UTC)
    page.reviewed_by_id = user.id
    if payload.review_status == "rejected":
        document.status = "needs_review"
    refresh_quality_from_existing_pages(db, document)
    write_audit(
        db,
        user=user,
        action="ocr_review_page_updated",
        entity_type="document_page",
        entity_id=page.id,
        details={
            "document_id": document.id,
            "page_number": page.page_number,
            "review_status": payload.review_status,
        },
    )
    db.commit()
    db.refresh(page)
    db.refresh(document)
    return _ocr_review_payload(page, document)


@router.post("/quality/pages/{page_id}/reprocess-ocr", response_model=JobActionResponse)
def reprocess_ocr_page(
    page_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ExtractionJob:
    page = db.get(DocumentPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="OCR review page not found")
    document = _get_or_404(db, Document, page.document_id, "Document not found")
    job = reprocess_document_page(db, page=page, user=user)
    write_audit(
        db,
        user=user,
        action="ocr_page_reprocess_requested",
        entity_type="document_page",
        entity_id=page.id,
        details={"document_id": document.id, "page_number": page.page_number, "job_id": job.id},
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/ocr-errors", response_model=list[DocumentRead])
def ocr_errors(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))
) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status.in_(["failed", "needs_review"]))
            .order_by(Document.created_at.desc())
            .limit(100)
        ).all()
    )


@router.get("/duplicates", response_model=list[DocumentRead])
def duplicates(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))
) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "duplicate")
            .order_by(Document.created_at.desc())
            .limit(100)
        ).all()
    )


@router.get("/quarantine-documents", response_model=list[DocumentRead])
def quarantine_documents(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .outerjoin(DocumentAccessMetadata, DocumentAccessMetadata.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(
                (DocumentAccessMetadata.id.is_(None))
                | (DocumentAccessMetadata.assignment_status != "assigned")
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        ).all()
    )
