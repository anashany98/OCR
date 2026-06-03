from pathlib import Path
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, DocumentBlock, DocumentEntity, DocumentPage, User
from app.schemas.documents import (
    BulkReprocessRequest,
    BulkReprocessResponse,
    DocumentBlockRead,
    DocumentEntityRead,
    DocumentPageRead,
    DocumentRead,
    UploadResponse,
)
from app.schemas.jobs import ExtractionJobRead
from app.services.audit import write_audit
from app.services.document_service import register_upload, reprocess_document, soft_delete_document
from app.services.operations import BulkReprocessFilters, bulk_reprocess_documents
from app.services.tenant_access import can_access_document, filter_documents_for_scope, resolve_user_access_scope

router = APIRouter()

logger = logging.getLogger(__name__)


class BatchUploadItem(BaseModel):
    document_id: int
    original_filename: str
    status: str
    job_id: int | None


class BatchUploadResponse(BaseModel):
    uploaded: int
    duplicates: int
    failed: int
    documents: list[BatchUploadItem]


@router.post("/upload", response_model=UploadResponse)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> UploadResponse:
    try:
        document, job = register_upload(db, filename=file.filename, stream=file.file, user=user)
    except ValueError as exc:
        if "max_upload_size" in str(exc):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise
    return UploadResponse(document=DocumentRead.model_validate(document), job_id=job.id if job else None)


@router.post("/upload/batch", response_model=BatchUploadResponse)
def upload_batch(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    uploaded = 0
    duplicates = 0
    failed = 0
    results = []

    for file in files:
        try:
            document, job = register_upload(db, filename=file.filename, stream=file.file, user=user, enqueue=True)
            if document.status == "duplicate":
                duplicates += 1
            else:
                uploaded += 1
            results.append(
                BatchUploadItem(
                    document_id=document.id,
                    original_filename=document.original_filename,
                    status=document.status,
                    job_id=job.id if job else None,
                )
            )
        except Exception as exc:
            logger.exception("batch_upload_failed filename=%s", file.filename)
            failed += 1

    db.commit()
    return BatchUploadResponse(uploaded=uploaded, duplicates=duplicates, failed=failed, documents=results)


@router.get("", response_model=list[DocumentRead])
def list_documents(
    status: str | None = None,
    document_type: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Document]:
    stmt = select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc())
    if status:
        stmt = stmt.where(Document.status == status)
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if q:
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Document.original_filename.ilike(f"%{escaped_q}%"))
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.offset(offset).limit(limit)).all())
    candidates = list(db.scalars(stmt.limit(max(limit + offset, 500))).all())
    return filter_documents_for_scope(db, candidates, scope)[offset : offset + limit]


@router.post("/reprocess-bulk", response_model=BulkReprocessResponse)
def reprocess_bulk(
    payload: BulkReprocessRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> BulkReprocessResponse:
    try:
        result = bulk_reprocess_documents(
            db,
            filters=BulkReprocessFilters(**payload.model_dump()),
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkReprocessResponse(
        matched=result.matched,
        enqueued=result.enqueued,
        skipped=result.skipped,
        job_ids=result.job_ids,
        mode=result.mode,
    )


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Document:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{document_id}/pages", response_model=list[DocumentPageRead])
def get_document_pages(document_id: int, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[DocumentPage]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return list(
        db.scalars(
            select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number.asc()).offset(offset).limit(limit)
        ).all()
    )


@router.get("/{document_id}/pages/{page_number}/image")
def get_document_page_image(
    document_id: int,
    page_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .where(DocumentPage.page_number == page_number)
    )
    if not page or not page.image_path:
        raise HTTPException(status_code=404, detail="Page preview not found")
    path = _resolve_files_dir_path(page.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Page preview not found")
    return FileResponse(path)


@router.get("/{document_id}/blocks", response_model=list[DocumentBlockRead])
def get_document_blocks(
    document_id: int,
    page_number: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentBlock]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    stmt = select(DocumentBlock).where(DocumentBlock.document_id == document_id).order_by(DocumentBlock.page_number.asc())
    if page_number:
        stmt = stmt.where(DocumentBlock.page_number == page_number)
    return list(db.scalars(stmt.offset(offset).limit(limit)).all())


@router.get("/{document_id}/entities", response_model=list[DocumentEntityRead])
def get_document_entities(
    document_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentEntity]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return list(
        db.scalars(
            select(DocumentEntity).where(DocumentEntity.document_id == document_id).order_by(DocumentEntity.entity_type.asc()).offset(offset).limit(limit)
        ).all()
    )


@router.post("/{document_id}/reprocess", response_model=ExtractionJobRead)
def reprocess(
    document_id: int,
    mode: Literal["full", "ocr", "text", "classification", "entities", "chunks", "embeddings"] = Query(default="full"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    job_type = "reprocess" if mode == "full" else f"reprocess:{mode}"
    job = reprocess_document(db, document=document, user=user, job_type=job_type)
    return job


@router.delete("/{document_id}", response_model=DocumentRead)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> Document:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    return soft_delete_document(db, document=document, user=user)


@router.get("/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)) or not document.stored_filename:
        raise HTTPException(status_code=404, detail="Document not found")
    path = (settings.files_dir / document.stored_filename).resolve()
    if not path.exists() or settings.files_dir.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Stored file not found")
    write_audit(db, user=user, action="document_downloaded", entity_type="document", entity_id=document.id)
    db.commit()
    return FileResponse(path, filename=document.original_filename, media_type=document.mime_type or "application/octet-stream")


def _resolve_files_dir_path(stored_path: str) -> Path:
    root = settings.files_dir.resolve()
    candidate = Path(stored_path)
    path = candidate.resolve() if candidate.is_absolute() else (root / stored_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Stored file not found") from None
    if path.is_symlink():
        raise HTTPException(status_code=404, detail="Stored file not found")
    return path
