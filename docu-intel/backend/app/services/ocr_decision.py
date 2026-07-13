"""Deterministic, auditable acceptance policy for OCR candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings
from app.ocr.base import OCRResult


@dataclass(frozen=True)
class OCRDecision:
    calibrated_confidence: float
    quality_score: float
    decision: str
    reasons: list[str]


def text_quality(text: str | None) -> float:
    clean = (text or "").strip()
    if not clean:
        return 0.0
    alnum = sum(char.isalnum() for char in clean)
    density = alnum / max(len(clean), 1)
    return max(0.0, min(1.0, density * 0.55 + min(len(clean) / 500, 1.0) * 0.45))


def _tokens(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _agreement(candidate: str | None, baseline: str | None) -> float:
    left, right = _tokens(candidate), _tokens(baseline)
    if not left or not right:
        return 0.5
    return len(left & right) / len(left | right)


def _has_numeric_conflict(candidate: str | None, baseline: str | None, baseline_confidence: float | None) -> bool:
    if baseline_confidence is None or baseline_confidence < 0.5:
        return False
    left = set(re.findall(r"\d+(?:[.,]\d+)?", candidate or ""))
    right = set(re.findall(r"\d+(?:[.,]\d+)?", baseline or ""))
    return bool(left and right and left != right and not (left & right))


def decide_ocr_result(result: OCRResult, *, baseline: OCRResult | None = None) -> OCRDecision:
    """Return a conservative decision without trusting VLM self-reporting.

    Native confidences contribute when present.  For VLM outputs without one,
    the text evidence and agreement with a usable preceding candidate provide
    an explicit, reviewable provisional confidence instead of silently
    treating ``None`` as successful OCR.
    """
    quality = text_quality(result.text)
    raw = result.confidence
    agreement = _agreement(result.text, baseline.text if baseline else None)
    if raw is None:
        calibrated = quality * 0.70 + agreement * 0.30
        reasons = ["derived_confidence"]
    else:
        calibrated = raw * 0.65 + quality * 0.25 + agreement * 0.10
        reasons = ["engine_confidence"]
    if _has_numeric_conflict(result.text, baseline.text if baseline else None, baseline.confidence if baseline else None):
        return OCRDecision(calibrated, quality, "review_required", reasons + ["numeric_conflict"])
    baseline_quality = text_quality(baseline.text) if baseline else 0.0
    if not (result.text or "").strip():
        return OCRDecision(calibrated, quality, "review_required", reasons + ["empty_text"])
    if calibrated < settings.ocr_auto_accept_confidence:
        return OCRDecision(calibrated, quality, "review_required", reasons + ["below_acceptance_threshold"])
    if baseline is not None and quality < baseline_quality + settings.ocr_auto_accept_improvement:
        return OCRDecision(calibrated, quality, "review_required", reasons + ["insufficient_improvement"])
    return OCRDecision(calibrated, quality, "auto_accepted", reasons + ["acceptance_threshold_met"])
