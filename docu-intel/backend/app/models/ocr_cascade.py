"""Per-tier attempt log for the cascading OCR engine.

The :class:`~app.ocr.cascading.CascadingOCREngine` tries up to four
tiers per page (Tesseract → PaddleOCR → PP-Structure → VLM). This
table records **every** attempt with its outcome so the admin UI can
reconstruct the full cascade trace (e.g. "page 3: Tesseract tried
and failed on quality, PaddleOCR succeeded with 0.83 confidence
after 412 ms").

One row per tier tried, per page. The winning tier is not special —
it just has ``success=True``; ``DocumentPage.ocr_engine`` continues
to be the single source of truth for "which engine's text is
stored".
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class OcrCascadeAttempt(Base):
    __tablename__ = "ocr_cascade_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_id: Mapped[int] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    # Engine name (``tesseract``, ``paddleocr``, ``pp_structure``, ``vlm_ocr``).
    tier: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # Order in the cascade: 1=primary, 2=fallback, 3=pp_structure, 4=vlm.
    tier_index: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Engine-reported confidence (NULL when the engine raised or the
    # attempt did not produce a usable result).
    confidence: Mapped[float | None] = mapped_column(Float)
    # Length of the engine's text output (used by the cascade to
    # decide whether to escalate; we persist it for forensics).
    chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Short reason label: ``"ok"``, ``"no_improvement"``, ``"exception"``,
    # ``"below_quality_threshold"`` … same labels already used in
    # :func:`app.ocr.cascading._should_replace_with_fallback`.
    reason: Mapped[str | None] = mapped_column(String(80))
    # Exception text when ``success=False`` and there was a real exception.
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


__all__ = ["OcrCascadeAttempt"]
