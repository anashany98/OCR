from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, User
from app.services.tenant_access import can_access_document, resolve_user_access_scope
from app.services.thumbnail import (
    generate_cad_preview,
    generate_cad_thumbnail,
    generate_eml_preview,
    generate_eml_thumbnail,
    generate_excel_thumbnail,
    generate_image_preview,
    generate_image_thumbnail,
    generate_msg_thumbnail,
    generate_office_thumbnail,
    generate_pdf_thumbnail,
    get_preview_path,
    get_thumbnail_path,
)

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
    elif document.extension in {".eml"}:
        thumb_relative = generate_eml_thumbnail(stored_path, document.file_hash)
    elif document.extension in {".dxf", ".dwg"}:
        thumb_relative = generate_cad_thumbnail(stored_path, document.file_hash)
    elif document.extension in {".doc", ".docx", ".odt", ".rtf"}:
        thumb_relative = generate_office_thumbnail(stored_path, document.file_hash)
    else:
        raise HTTPException(status_code=404, detail="No thumbnail available for this file type")

    if not thumb_relative:
        raise HTTPException(status_code=404, detail="Failed to generate thumbnail")

    thumb_path = settings.files_dir / thumb_relative
    return FileResponse(thumb_path, media_type="image/jpeg")


@router.get("/{document_id}/preview")
def get_document_preview(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a full-size generated preview for mail and CAD documents."""
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    preview_relative = get_preview_path(document.file_hash)
    if preview_relative:
        return FileResponse(settings.files_dir / preview_relative, media_type="image/jpeg")
    if not document.stored_filename:
        raise HTTPException(status_code=404, detail="File not found")
    stored_path = settings.files_dir / document.stored_filename
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if document.extension == ".eml":
        preview_relative = generate_eml_preview(stored_path, document.file_hash)
    elif document.extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        preview_relative = generate_image_preview(stored_path, document.file_hash)
    elif document.extension in {".dxf", ".dwg"}:
        preview_relative = generate_cad_preview(stored_path, document.file_hash)
    else:
        raise HTTPException(status_code=404, detail="No preview available for this file type")
    if not preview_relative:
        raise HTTPException(status_code=404, detail="Failed to generate preview")
    return FileResponse(settings.files_dir / preview_relative, media_type="image/jpeg")
