"""Cascading OCR engine.

Strategy:
  1. Try the cheap primary engine (Tesseract) on the image.
  2. If the primary result is "good enough" (text length and average
     confidence above the configured thresholds), return it.
  3. Otherwise try the heavy fallback (PaddleOCR). PaddleOCR loads its
     model lazily on the first escalation, so easy documents never pay
     the init cost.
  4. The fallback result replaces the primary one only when its quality
     score beats the current best result. The score combines confidence,
     useful-character density and a saturated length factor.
  5. **Optional Tier 3**: if ``pp_structure`` is wired in and both
     Tier 1 and Tier 2 produced weak results, escalate to PP-Structure
     (PaddleX layout_parsing). Tier 3 is GPU-only and only fires on
     the hardest cases so we don't pay the ~500 MB model download on
     every page. Tier 3 also wins by quality score, not raw text length.

The cascaded :attr:`name` is updated on every call to reflect which
engine produced the winning result, so the admin UI can break down the
share of pages that escalated to Paddle / PP-Structure.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from app.ocr.base import BaseOCREngine, OCRResult
from app.services.metrics import track_ocr_cascade_fallback, track_ocr_duration, track_ocr_tier_used


logger = logging.getLogger("app.ocr.cascading")
QUALITY_EPSILON = 0.01


def _quality(result: OCRResult) -> float:
    text = (result.text or "").strip()
    if not text:
        return 0.0
    alnum = sum(1 for char in text if char.isalnum() or char.isspace())
    density = alnum / max(len(text), 1)
    confidence = result.confidence if result.confidence is not None else 0.5
    confidence = max(0.0, min(1.0, confidence))
    length_factor = min(len(text) / 500.0, 1.0)
    return confidence * 0.5 + density * 0.3 + length_factor * 0.2


class CascadingOCREngine:
    """Try a cheap primary first, fall back to a heavy secondary on weak results.

    The cascade is transparent to callers: it implements
    :class:`BaseOCREngine` (duck-typed via :data:`BaseOCREngine` Protocol)
    and exposes a dynamic ``name`` that mirrors whichever engine produced
    the last result.
    """

    def __init__(
        self,
        primary: BaseOCREngine,
        fallback: BaseOCREngine,
        *,
        min_chars: int = 30,
        min_confidence: float = 0.5,
        pp_structure: BaseOCREngine | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.pp_structure = pp_structure
        self.min_chars = min_chars
        self.min_confidence = min_confidence
        # ``name`` is the engine identity of the last result; default to
        # the primary so a query before any call still has a sensible
        # value.
        self._name: str = primary.name

    @property
    def name(self) -> str:
        return self._name

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        primary_result = self.primary.extract(image_path)
        track_ocr_duration(time.perf_counter() - start)

        if self._is_acceptable(primary_result):
            return self._record_winner(self.primary.name, primary_result)

        # Escalate to the fallback. Any failure here is best-effort:
        # we keep the primary result so the user at least sees *some*
        # text instead of a blank page. The vision LLM fallback further
        # downstream catches the truly impossible cases.
        start = time.perf_counter()
        try:
            fallback_result = self.fallback.extract(image_path)
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.fallback.name, exc)
            return self._record_winner(self.primary.name, primary_result)
        track_ocr_duration(time.perf_counter() - start)

        if self._is_better(fallback_result, primary_result):
            # Tier 2 won — try Tier 3 only if it's wired in AND Tier 2
            # is still weak (below thresholds). Otherwise return Tier 2.
            if self.pp_structure is not None and not self._is_acceptable(fallback_result):
                tier3 = self._try_tier3(image_path, primary_result, fallback_result)
                if tier3 is not None:
                    return tier3
            return self._record_winner(self.fallback.name, fallback_result)

        # Tier 2 didn't beat Tier 1 — try Tier 3 if available.
        if self.pp_structure is not None:
            tier3 = self._try_tier3(image_path, primary_result, fallback_result)
            if tier3 is not None:
                return tier3

        return self._record_winner(self.primary.name, primary_result)

    def _try_tier3(
        self,
        image_path: Path,
        primary_result: OCRResult,
        fallback_result: OCRResult,
    ) -> OCRResult | None:
        """Run PP-Structure on the page. Returns the best of the three
        results, or ``None`` if Tier 3 failed / didn't beat the others.

        PP-Structure init is expensive (~5-10 s on first call) and the
        model is heavy, so we keep the try/except tight: any failure
        falls back to whichever of Tier 1 / Tier 2 is better.
        """
        assert self.pp_structure is not None  # caller-guaranteed
        start = time.perf_counter()
        try:
            tier3_result = self.pp_structure.extract(image_path)
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.pp_structure.name, exc)
            return None
        track_ocr_duration(time.perf_counter() - start)

        # PP-Structure is also judged on text length; a run that
        # returned nothing useful should never replace a Tier 2 result.
        if not tier3_result.text or len(tier3_result.text.strip()) < self.min_chars:
            return None

        best_prior = fallback_result if self._is_better(fallback_result, primary_result) else primary_result
        if self._is_better(tier3_result, best_prior):
            return self._record_winner(self.pp_structure.name, tier3_result)
        return None

    def _is_acceptable(self, result: OCRResult) -> bool:
        """A primary result is acceptable when it has enough text and
        a confidence above the configured floor."""
        if not result.text or len(result.text.strip()) < self.min_chars:
            return False
        if result.confidence is not None and result.confidence < self.min_confidence:
            return False
        return True

    def _is_better(self, candidate: OCRResult, baseline: OCRResult) -> bool:
        """Decide whether the fallback result should replace the primary.

        The candidate must beat the baseline on quality by a small margin.
        Length is only one saturated component of the score, so noisy OCR
        cannot win just by emitting more characters.
        """
        return _quality(candidate) > _quality(baseline) + QUALITY_EPSILON

    def _record_winner(self, tier: str, result: OCRResult) -> OCRResult:
        self._name = tier
        track_ocr_tier_used(tier)
        return result

    def _track_fallback_failure(self, engine_name: str, exc: Exception) -> None:
        reason = str(exc) or exc.__class__.__name__
        logger.warning("OCR cascade engine %s failed: %s", engine_name, reason)
        track_ocr_cascade_fallback(engine_name, reason)


__all__ = ["CascadingOCREngine", "_quality"]
