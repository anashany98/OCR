"""Admin endpoints for OCR engine visibility.

Mounted at ``/admin/ocr-stats`` so it's discoverable in the OpenAPI spec.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import DocumentPage, User

router = APIRouter()


@router.get("/admin/ocr-stats")
def ocr_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    """Counts of pages grouped by OCR engine and the share routed to PaddleOCR.

    Useful for verifying that the "skip OCR for digital PDFs" path is actually
    being taken. A high paddleocr share is a smell — either the source PDFs
    are scanned, or the threshold is wrong.
    """
    rows = db.execute(
        select(DocumentPage.ocr_engine, func.count(DocumentPage.id)).group_by(DocumentPage.ocr_engine)
    ).all()
    counts: dict[str, int] = {}
    for engine, count in rows:
        key = engine or "unset"
        counts[key] = int(count)

    total = sum(counts.values())
    paddleocr = counts.get("paddleocr", 0)
    pymupdf = counts.get("pymupdf", 0)
    empty = counts.get("empty", 0)
    share = {
        "paddleocr": round(paddleocr / total, 4) if total else 0.0,
        "pymupdf": round(pymupdf / total, 4) if total else 0.0,
        "empty": round(empty / total, 4) if total else 0.0,
    }
    return {
        "total_pages": total,
        "counts": counts,
        "share": share,
    }
