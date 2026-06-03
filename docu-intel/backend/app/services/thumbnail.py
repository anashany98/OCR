from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.core.config import settings

THUMBNAIL_SIZE = (200, 280)
THUMBNAIL_DIR = settings.files_dir / "thumbnails"


def ensure_thumbnail_dir() -> Path:
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    return THUMBNAIL_DIR


def generate_pdf_thumbnail(pdf_path: Path, document_hash: str) -> Path | None:
    try:
        import pymupdf

        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"

        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)

        doc = pymupdf.open(str(pdf_path))
        if doc.page_count == 0:
            return None

        page = doc[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
        img_data = pix.tobytes("jpg")

        img = Image.open(io.BytesIO(img_data))
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        img.save(thumb_path, "JPEG", quality=85)

        doc.close()
        return thumb_path.relative_to(settings.files_dir)
    except Exception:
        return None


def generate_image_thumbnail(image_path: Path, document_hash: str) -> Path | None:
    try:
        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"

        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)

        img = Image.open(str(image_path))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        img.save(thumb_path, "JPEG", quality=85)

        return thumb_path.relative_to(settings.files_dir)
    except Exception:
        return None


def get_thumbnail_path(document_hash: str) -> Path | None:
    thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
    if thumb_path.exists():
        return thumb_path.relative_to(settings.files_dir)
    return None
