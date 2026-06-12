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
    """Counts of pages grouped by OCR engine and the share per backend.

    Useful for verifying that the cascade is doing the right thing: a
    high ``pymupdf`` share means the "skip OCR for digital PDFs" path
    is being taken, ``tesseract`` is the cheap primary that handles
    easy scans, ``paddleocr`` is the heavy fallback the cascade
    escalates to on hard cases, and ``pp_structure`` is the optional
    GPU-only Tier 3 for layout/table extraction. A persistently high
    ``paddleocr`` / ``pp_structure`` share is a smell — either the
    documents are unusually difficult or the cascade thresholds are
    too aggressive.
    """
    rows = db.execute(
        select(DocumentPage.ocr_engine, func.count(DocumentPage.id)).group_by(
            DocumentPage.ocr_engine
        )
    ).all()
    counts: dict[str, int] = {}
    for engine, count in rows:
        key = engine or "unset"
        counts[key] = int(count)

    total = sum(counts.values())
    tesseract = counts.get("tesseract", 0)
    paddleocr = counts.get("paddleocr", 0)
    pp_structure = counts.get("pp_structure", 0)
    pymupdf = counts.get("pymupdf", 0)
    empty = counts.get("empty", 0)
    vision = counts.get("vision", 0)
    # Aggregate "had to run any OCR at all" for at-a-glance visibility.
    ocr_total = tesseract + paddleocr + pp_structure + vision
    share = {
        "tesseract": round(tesseract / total, 4) if total else 0.0,
        "paddleocr": round(paddleocr / total, 4) if total else 0.0,
        "pp_structure": round(pp_structure / total, 4) if total else 0.0,
        "pymupdf": round(pymupdf / total, 4) if total else 0.0,
        "vision": round(vision / total, 4) if total else 0.0,
        "empty": round(empty / total, 4) if total else 0.0,
        "ocr_share": round(ocr_total / total, 4) if total else 0.0,
    }
    return {
        "total_pages": total,
        "counts": counts,
        "share": share,
    }
