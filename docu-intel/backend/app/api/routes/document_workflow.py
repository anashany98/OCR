from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import Document, DocumentPage, DocumentTimelineEvent, OcrRevision, User
from app.schemas.professional import DocumentTimelineEventRead, OcrRevisionCreate, OcrRevisionRead
from app.services.audit import write_audit
from app.services.tenant_access import can_access_document, resolve_user_access_scope

router = APIRouter()


@router.get("/{document_id}/timeline", response_model=list[DocumentTimelineEventRead])
def document_timeline(
    document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[DocumentTimelineEvent]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return list(
        db.scalars(
            select(DocumentTimelineEvent)
            .where(DocumentTimelineEvent.document_id == document_id)
            .order_by(DocumentTimelineEvent.created_at.desc())
        ).all()
    )


@router.post("/pages/{page_id}/ocr-revisions", response_model=OcrRevisionRead)
def create_ocr_revision(
    page_id: int,
    payload: OcrRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> OcrRevision:
    page = db.get(DocumentPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    document = db.get(Document, page.document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Page not found")
    revision = OcrRevision(
        page_id=page.id,
        document_id=page.document_id,
        original_text=page.text or "",
        corrected_text=payload.corrected_text,
        reason=payload.reason,
        created_by_id=user.id,
    )
    page.text = payload.corrected_text
    page.review_status = "pending"
    db.add(revision)
    db.add(
        DocumentTimelineEvent(
            document_id=page.document_id,
            event_type="ocr_revision",
            title="OCR corregido manualmente",
            description=payload.reason,
            actor_user_id=user.id,
            details_json={"page_id": page.id, "page_number": page.page_number},
            created_at=datetime.now(timezone.utc),
        )
    )
    write_audit(
        db, user=user, action="ocr_revision_created", entity_type="document_page", entity_id=page.id
    )
    db.commit()
    db.refresh(revision)
    return revision


@router.get("/pages/{page_id}/ocr-revisions", response_model=list[OcrRevisionRead])
def list_ocr_revisions(
    page_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[OcrRevision]:
    page = db.get(DocumentPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    document = db.get(Document, page.document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Page not found")
    return list(
        db.scalars(
            select(OcrRevision)
            .where(OcrRevision.page_id == page_id)
            .order_by(OcrRevision.created_at.desc())
        ).all()
    )
