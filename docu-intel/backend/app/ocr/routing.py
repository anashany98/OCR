"""Cheap content routing for pages that benefit from vision OCR first."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.ocr.base import OCRResult

_MANUSCRIPT_HINTS = ("manuscrit", "mano", "apunte", "nota", "croquis", "boceto", "sketch")


def manuscript_likelihood(path: Path, content_route: str | None = None) -> tuple[str, float]:
    """Return a bounded, fail-open manuscript likelihood without a new model."""
    hint = f"{path.name} {content_route or ''}".lower()
    if any(word in hint for word in _MANUSCRIPT_HINTS):
        return "manuscript", 0.90
    try:
        from app.parsers.clip_classifier import classify_image

        result = classify_image(path)
        category = result.get("category")
        confidence = float(result.get("confidence") or 0.0)
        if category == "plan":
            return "sketch_or_plan", min(0.80, confidence + 0.20)
        if category == "product_photo":
            return "photographed_note", min(0.75, confidence)
    except Exception:
        pass
    return "printed_or_unknown", 0.0


def should_route_manuscript_first(path: Path, content_route: str | None = None) -> tuple[str, bool]:
    kind, likelihood = manuscript_likelihood(path, content_route)
    return kind, likelihood >= settings.ocr_manuscript_route_threshold


@dataclass(frozen=True)
class OvisOCR2Eligibility:
    """Explainable, deterministic decision to offer a page to OvisOCR2."""

    eligible: bool
    reason: str


_NATIVE_ROUTES = frozenset({"native_text", "digital_native", "structured_parser"})
_COMPLEX_ROUTES = frozenset({"plan", "manuscript", "interior_design", "technical_document"})
_FORMULA_RE = re.compile(r"(?:\\\[|\$\$|\\\(|\$)[^\n]{2,}(?:\\\]|\$\$|\\\)|\$)")
_TABLE_RE = re.compile(r"<table\b|\|[^\n|]+\|[^\n|]+\|", re.IGNORECASE)


def stable_ovisocr2_canary(
    document_id: int | str | None, page_number: int | None, percent: int
) -> bool:
    """Return a stable canary assignment without high-cardinality state."""
    if percent <= 0 or document_id is None or page_number is None:
        return False
    if percent >= 100:
        return True
    key = f"{document_id}:{page_number}".encode("utf-8", "strict")
    bucket = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % 100
    return bucket < percent


def ovisocr2_eligibility(
    path: Path,
    *,
    baseline: OCRResult | None,
    content_route: str | None,
    document_id: int | str | None,
    page_number: int | None,
    canary_percent: int,
    tier4_primary: bool,
) -> OvisOCR2Eligibility:
    """Select only hard OCR pages, keeping native/cheap paths untouched.

    The function has no I/O and no random state, making production routing
    directly testable and repeatable for an exact document/page pair.
    """
    route = (content_route or "").strip().lower()
    if route in _NATIVE_ROUTES:
        return OvisOCR2Eligibility(False, "native_control")
    if stable_ovisocr2_canary(document_id, page_number, canary_percent):
        return OvisOCR2Eligibility(True, "stable_canary")
    if tier4_primary:
        return OvisOCR2Eligibility(True, "tier4_primary")
    text = (baseline.text if baseline else "") or ""
    if route in _COMPLEX_ROUTES:
        return OvisOCR2Eligibility(True, f"complex_route:{route}")
    if baseline is None or not text.strip():
        return OvisOCR2Eligibility(True, "empty_or_missing_ocr")
    if (
        baseline.confidence is not None
        and baseline.confidence < settings.low_ocr_confidence_threshold
    ):
        return OvisOCR2Eligibility(True, "low_ocr_confidence")
    if _TABLE_RE.search(text):
        return OvisOCR2Eligibility(True, "table_structure")
    if _FORMULA_RE.search(text):
        return OvisOCR2Eligibility(True, "formula_structure")
    name = path.name.lower()
    if any(hint in name for hint in ("plan", "croquis", "manuscrit", "formula", "tabla")):
        return OvisOCR2Eligibility(True, "filename_complexity_hint")
    return OvisOCR2Eligibility(False, "quality_control")


__all__ = [
    "OvisOCR2Eligibility",
    "manuscript_likelihood",
    "ovisocr2_eligibility",
    "should_route_manuscript_first",
    "stable_ovisocr2_canary",
]
