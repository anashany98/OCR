"""Cheap content routing for pages that benefit from vision OCR first."""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings

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
