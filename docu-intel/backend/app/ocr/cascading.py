"""Cascading OCR engine.

Strategy:
  1. Try the cheap primary engine (Tesseract) on the image.
  2. If the primary result is "good enough" (text length and average
     confidence above the configured thresholds), return it.
  3. Otherwise try the heavy fallback (PaddleOCR). PaddleOCR loads its
     model lazily on the first escalation, so easy documents never pay
     the init cost.
  4. The fallback result replaces the primary one whenever it has
     either more text or higher average confidence.

The cascaded :attr:`name` is updated on every call to reflect which
engine produced the winning result, so the admin UI can break down the
share of pages that escalated to Paddle.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import ClassVar

from app.ocr.base import BaseOCREngine, OCRResult
from app.services.metrics import track_ocr_duration


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
    ) -> None:
        self.primary = primary
        self.fallback = fallback
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
            self._name = self.primary.name
            return primary_result

        # Escalate to the fallback. Any failure here is best-effort:
        # we keep the primary result so the user at least sees *some*
        # text instead of a blank page. The vision LLM fallback further
        # downstream catches the truly impossible cases.
        start = time.perf_counter()
        try:
            fallback_result = self.fallback.extract(image_path)
        except Exception:
            self._name = self.primary.name
            return primary_result
        track_ocr_duration(time.perf_counter() - start)

        if self._is_better(fallback_result, primary_result):
            self._name = self.fallback.name
            return fallback_result

        self._name = self.primary.name
        return primary_result

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

        Heuristic: the fallback wins if it produced strictly more text
        OR strictly higher confidence. On a tie we keep the primary so
        we don't penalise fast pages by running paddle every time.
        """
        cand_chars = len((candidate.text or "").strip())
        base_chars = len((baseline.text or "").strip())
        cand_conf = candidate.confidence or 0.0
        base_conf = baseline.confidence or 0.0
        if cand_chars > base_chars and cand_chars > 0:
            return True
        if cand_conf > base_conf and cand_chars >= max(self.min_chars, base_chars // 2):
            return True
        return False


__all__ = ["CascadingOCREngine"]
