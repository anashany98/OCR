"""P1.1 — Cheap CPU probe for PDF documents.

Classifies a PDF as digital, mixed, or scanned before routing
to the appropriate Celery queue. The probe uses only CPU (no
GPU needed) and inspects the first few pages for:
- Number of pages
- Physical dimensions
- Embedded text in the first pages
- Estimated digital/scanned ratio
- Plan/document signals

Routes:
- digital  → text_fast  (CPU extraction, no OCR needed)
- mixed    → text_fast  (CPU text + OCR only for scanned pages)
- scanned  → ocr_heavy  (full OCR on GPU)
- plan     → ocr_heavy  (heavy route with layout analysis)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger("app.services.document_probe")


class DocumentRoute(Enum):
    DIGITAL = "digital"
    MIXED = "mixed"
    SCANNED = "scanned"
    PLAN = "plan"


@dataclass(frozen=True)
class ProbeResult:
    route: DocumentRoute
    page_count: int
    has_embedded_text: bool
    digital_ratio: float  # 0.0 = fully scanned, 1.0 = fully digital
    is_plan: bool
    reason: str


def probe_pdf(path: Path, *, timeout_seconds: float = 10.0) -> ProbeResult:
    """Classify a PDF document using cheap CPU inspection.

    Examines the first 3 pages for embedded text to estimate
    the digital/scanned ratio. Returns a ProbeResult with the
    recommended processing route.
    """
    try:
        return _probe_with_pymupdf(path, timeout_seconds=timeout_seconds)
    except Exception as exc:
        logger.warning(
            "PDF probe failed for %s: %s — defaulting to scanned route",
            path.name,
            exc,
        )
        return ProbeResult(
            route=DocumentRoute.SCANNED,
            page_count=0,
            has_embedded_text=False,
            digital_ratio=0.0,
            is_plan=False,
            reason="probe_failed_default_scanned",
        )


def _probe_with_pymupdf(path: Path, *, timeout_seconds: float = 10.0) -> ProbeResult:
    import fitz

    with fitz.open(str(path)) as pdf:
        page_count = len(pdf)
        if page_count == 0:
            return ProbeResult(
                route=DocumentRoute.SCANNED,
                page_count=0,
                has_embedded_text=False,
                digital_ratio=0.0,
                is_plan=False,
                reason="empty_pdf",
            )

        # Sample first 3 pages (or fewer)
        sample_pages = min(3, page_count)
        pages_with_text = 0
        total_chars = 0

        for i in range(sample_pages):
            page = pdf[i]
            text = page.get_text("text").strip()
            char_count = len(text)
            total_chars += char_count
            if char_count > 50:  # Meaningful text threshold
                pages_with_text += 1

        digital_ratio = pages_with_text / sample_pages if sample_pages > 0 else 0.0
        has_embedded_text = total_chars > 100

        # Check for plan signals in text
        is_plan = False
        if has_embedded_text:
            sample_text = ""
            for i in range(min(2, page_count)):
                sample_text += pdf[i].get_text("text")
            is_plan = _detect_plan_signals(sample_text)

        # Route classification
        if is_plan:
            route = DocumentRoute.PLAN
            reason = "plan_signals_detected"
        elif digital_ratio >= 0.8:
            route = DocumentRoute.DIGITAL
            reason = f"digital_ratio={digital_ratio:.2f}"
        elif digital_ratio > 0.0:
            route = DocumentRoute.MIXED
            reason = f"digital_ratio={digital_ratio:.2f}"
        else:
            route = DocumentRoute.SCANNED
            reason = "no_embedded_text"

        return ProbeResult(
            route=route,
            page_count=page_count,
            has_embedded_text=has_embedded_text,
            digital_ratio=digital_ratio,
            is_plan=is_plan,
            reason=reason,
        )


def _detect_plan_signals(text: str) -> bool:
    """Check for architectural/plan signals in text."""
    import re

    normalized = text.lower()
    # Scale patterns: 1:100, 1/50, etc.
    if re.search(r"\b(?:escala\s*)?1\s*[:/]\s*\d{1,5}\b", normalized):
        return True
    # Plan keywords
    plan_keywords = {"escala", "planta", "cota", "cotas", "alzado", "seccion"}
    hits = sum(1 for kw in plan_keywords if kw in normalized)
    return hits >= 2
