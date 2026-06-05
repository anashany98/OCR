from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, User
from app.services.thumbnail import (
    generate_excel_thumbnail,
    generate_image_thumbnail,
    generate_msg_thumbnail,
    generate_pdf_thumbnail,
    get_thumbnail_path,
)
from app.services.tenant_access import can_access_document, resolve_user_access_scope

router = APIRouter()


@router.get("/{document_id}/thumbnail")
def get_document_thumbnail(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")

    thumb_relative = get_thumbnail_path(document.file_hash)
    if thumb_relative:
        thumb_path = settings.files_dir / thumb_relative
        return FileResponse(thumb_path, media_type="image/jpeg")

    if not document.stored_filename:
        raise HTTPException(status_code=404, detail="File not found")
    stored_path = settings.files_dir / document.stored_filename
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if document.extension in {".pdf"}:
        thumb_relative = generate_pdf_thumbnail(stored_path, document.file_hash)
    elif document.extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        thumb_relative = generate_image_thumbnail(stored_path, document.file_hash)
    elif document.extension in {".xlsx", ".xls", ".xlsm"}:
        thumb_relative = generate_excel_thumbnail(stored_path, document.file_hash)
    elif document.extension in {".msg"}:
        thumb_relative = generate_msg_thumbnail(stored_path, document.file_hash)
    else:
        raise HTTPException(status_code=404, detail="No thumbnail available for this file type")

    if not thumb_relative:
        raise HTTPException(status_code=404, detail="Failed to generate thumbnail")

    thumb_path = settings.files_dir / thumb_relative
    return FileResponse(thumb_path, media_type="image/jpeg")
