"""Cascading OCR engine.

Strategy:
  1. Try the cheap primary engine (Tesseract) on the image.
  2. If the primary result is "good enough" (text length and average
     confidence above the configured thresholds), return it.
  3. Otherwise try the heavy fallback (PaddleOCR). PaddleOCR loads its
     model lazily on the first escalation, so easy documents never pay
     the init cost.
  4. The fallback result replaces the primary one only when its quality
     score beats the current best result by a *significant* margin
     (configurable, default delta 0.10) or it adds at least
     ``ocr_cascading_skip_alnum_gain`` alphanumeric characters. This
     keeps the cascade from spending GPU on a marginal improvement.
  5. **Optional Tier 3**: if ``pp_structure`` is wired in and both
     Tier 1 and Tier 2 produced weak results, escalate to PP-Structure
     (PaddleX layout_parsing). Tier 3 is GPU-only and only fires on
     the hardest cases so we don't pay the ~500 MB model download on
     every page. Tier 3 also wins by quality score, not raw text length.
  6. **Optional Tier 4 (VLM OCR)**: if ``vlm_ocr`` is wired in and the
     best Tier 1-3 result is still below ``tier4_quality_threshold``,
     ask a vision LLM to transcribe the page. Only used as a last
     resort; cost is 5-10s on a local vision model.

The cascaded :attr:`name` is updated on every call to reflect which
engine produced the winning result, so the admin UI can break down the
share of pages that escalated to Paddle / PP-Structure.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine, OCRResult, extract_with_language_hint
from app.services.metrics import (
    track_ocr_cascade_fallback,
    track_ocr_duration,
    track_ocr_language_threshold_used,
    track_ocr_skip_tier2,
    track_ocr_tier_used,
)
from app.services.ocr_language import LanguageThresholds, thresholds_for


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


def _alnum_count(text: str | None) -> int:
    if not text:
        return 0
    return sum(1 for char in text if char.isalnum())


def _should_replace_with_fallback(
    primary: OCRResult,
    fallback: OCRResult,
) -> tuple[bool, str]:
    """Decide whether the Tier 2 fallback should replace the primary.

    Returns ``(True, "ok")`` when the cascade should swap, or
    ``(False, "<reason>")`` when the primary should be kept. The reason
    is a short label that is also exposed as a Prometheus counter so
    the admin UI can break down *why* the cascade skipped Tier 2 on any
    given page.

    The decision is governed by two settings:

    * ``ocr_cascading_skip_if_no_significant_gain`` (default True):
      when False the function falls back to the legacy behaviour of
      "any quality improvement wins" (a single ``QUALITY_EPSILON``
      delta is enough).
    * ``ocr_cascading_skip_quality_improvement`` (default 0.10): the
      minimum delta on the combined quality score for the fallback to
      be considered a "significant" win.
    * ``ocr_cascading_skip_alnum_gain`` (default 30): the fallback can
      also win when it adds at least this many alphanumeric characters,
      even if the quality delta is small (covers the noisy-OCR case
      where density is high but the actual letters are wrong).
    """
    primary_quality = _quality(primary)
    fallback_quality = _quality(fallback)
    quality_delta = fallback_quality - primary_quality

    # Both results are basically noise: keep the primary so the user
    # sees *some* text (even if it is wrong) instead of swapping it
    # for equally-wrong Tier 2 output.
    if fallback_quality <= QUALITY_EPSILON and primary_quality <= QUALITY_EPSILON:
        return False, "both_weak"

    if not settings.ocr_cascading_skip_if_no_significant_gain:
        # Legacy behaviour: any positive delta wins.
        if quality_delta > QUALITY_EPSILON:
            return True, "ok"
        return False, "no_improvement"

    primary_alnum = _alnum_count(primary.text)
    fallback_alnum = _alnum_count(fallback.text)
    alnum_gain = fallback_alnum - primary_alnum

    if quality_delta >= settings.ocr_cascading_skip_quality_improvement:
        return True, "ok"
    if alnum_gain >= settings.ocr_cascading_skip_alnum_gain:
        return True, "alnum_gain"
    if quality_delta <= 0.0:
        return False, "no_improvement"
    if quality_delta < settings.ocr_cascading_skip_quality_improvement:
        return False, "no_significant_gain"
    return False, "no_improvement"


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
        vlm_ocr: BaseOCREngine | None = None,
        tier4_quality_threshold: float = 0.62,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.pp_structure = pp_structure
        self.vlm_ocr = vlm_ocr
        self.min_chars = min_chars
        self.min_confidence = min_confidence
        self.tier4_quality_threshold = tier4_quality_threshold
        # ``name`` is the engine identity of the last result; default to
        # the primary so a query before any call still has a sensible
        # value.
        self._name: str = primary.name

    @property
    def name(self) -> str:
        return self._name

    def extract(
        self,
        image_path: Path,
        *,
        language: str | None = None,
    ) -> OCRResult:
        """Run the cascade on a single image.

        The ``language`` keyword is the detected page language
        (e.g. ``"es"``, ``"en"``). It is used to look up the
        per-language adaptive thresholds (O2) when the
        setting ``ocr_cascading_use_adaptive_thresholds`` is
        on. ``None`` means "no detection", and the cascade
        falls back to the document-wide ``self.min_chars`` /
        ``self.min_confidence`` constants.

        ``language`` is passed as a parameter (not stored on
        ``self``) so two threads can run the cascade in
        parallel — the previous design stored the language
        on ``self.current_language`` and the parser had to
        set it via ``setattr`` before each call, which
        raced when multiple pages were processed in
        parallel.
        """
        start = time.perf_counter()
        primary_result = extract_with_language_hint(
            self.primary,
            image_path,
            language=language,
        )
        track_ocr_duration(time.perf_counter() - start)

        if self._is_acceptable(primary_result, language=language):
            return self._finalize(image_path, self.primary.name, primary_result, language)

        # Escalate to the fallback. Any failure here is best-effort:
        # we keep the primary result so the user at least sees *some*
        # text instead of a blank page. The vision LLM fallback further
        # downstream catches the truly impossible cases.
        start = time.perf_counter()
        try:
            fallback_result = extract_with_language_hint(
                self.fallback,
                image_path,
                language=language,
            )
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.fallback.name, exc)
            return self._finalize(image_path, self.primary.name, primary_result, language)
        track_ocr_duration(time.perf_counter() - start)

        should_replace, reason = _should_replace_with_fallback(primary_result, fallback_result)
        if should_replace:
            # Tier 2 won — try Tier 3 only if it's wired in AND Tier 2
            # is still weak (below thresholds). Otherwise return Tier 2.
            if self.pp_structure is not None and not self._is_acceptable(
                fallback_result, language=language
            ):
                tier3 = self._try_tier3(image_path, primary_result, fallback_result, language)
                if tier3 is not None:
                    return self._finalize(
                        image_path,
                        self.pp_structure.name if self.pp_structure else self._name,
                        tier3,
                        language,
                    )
            return self._finalize(image_path, self.fallback.name, fallback_result, language)

        # S0.6 — record why the cascade kept the primary result instead
        # of paying for the Tier 2 win. The Prometheus label lets the
        # admin UI distinguish "fallback was barely better" (the common
        # case) from "both engines failed" (the rare, harder case).
        track_ocr_skip_tier2(reason)
        logger.info(
            "OCR skip Tier 2: image=%s primary_chars=%d fallback_chars=%d "
            "primary_quality=%.3f fallback_quality=%.3f reason=%s",
            image_path.name,
            len((primary_result.text or "").strip()),
            len((fallback_result.text or "").strip()),
            _quality(primary_result),
            _quality(fallback_result),
            reason,
        )

        # Tier 2 didn't beat Tier 1 — try Tier 3 if available.
        if self.pp_structure is not None:
            tier3 = self._try_tier3(image_path, primary_result, fallback_result, language)
            if tier3 is not None:
                return self._finalize(image_path, self.pp_structure.name, tier3, language)

        return self._finalize(image_path, self.primary.name, primary_result, language)

    def _try_tier3(
        self,
        image_path: Path,
        primary_result: OCRResult,
        fallback_result: OCRResult,
        language: str | None = None,
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
            tier3_result = extract_with_language_hint(
                self.pp_structure,
                image_path,
                language=language,
            )
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.pp_structure.name, exc)
            return None
        track_ocr_duration(time.perf_counter() - start)

        # PP-Structure is also judged on text length; a run that
        # returned nothing useful should never replace a Tier 2 result.
        if not tier3_result.text or len(tier3_result.text.strip()) < self.min_chars:
            return None

        best_prior = (
            fallback_result if self._is_better(fallback_result, primary_result) else primary_result
        )
        if self._is_better(tier3_result, best_prior):
            return tier3_result
        return None

    def _finalize(
        self,
        image_path: Path,
        tier: str,
        result: OCRResult,
        language: str | None = None,
    ) -> OCRResult:
        if self.vlm_ocr is None or _quality(result) >= self.tier4_quality_threshold:
            return self._record_winner(tier, result)
        tier4_result = self._try_tier4(image_path, result, language)
        if tier4_result is not None:
            return tier4_result
        return self._record_winner(tier, result)

    def _try_tier4(
        self,
        image_path: Path,
        best_prior: OCRResult,
        language: str | None = None,
    ) -> OCRResult | None:
        assert self.vlm_ocr is not None
        start = time.perf_counter()
        try:
            tier4_result = extract_with_language_hint(
                self.vlm_ocr,
                image_path,
                language=language,
            )
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.vlm_ocr.name, exc)
            return None
        track_ocr_duration(time.perf_counter() - start)

        if self._is_better(tier4_result, best_prior):
            return self._record_winner(self.vlm_ocr.name, tier4_result)
        return None

    def _is_acceptable(
        self,
        result: OCRResult,
        *,
        language: str | None = None,
    ) -> bool:
        """A primary result is acceptable when it has enough text and
        a confidence above the configured floor.

        The thresholds come from :data:`settings.ocr_cascading_*`
        unless O2 adaptive thresholds are enabled, in which case
        they are looked up per detected language via
        :func:`app.services.ocr_language.thresholds_for`. The
        lookup result is exposed through the
        ``track_ocr_language_threshold_used`` counter so the admin
        UI can show which thresholds are actually firing.
        """
        thresholds = self._thresholds_for_language(language)
        if not result.text or len(result.text.strip()) < thresholds.min_chars:
            return False
        if result.confidence is not None and result.confidence < thresholds.min_confidence:
            return False
        return True

    def _thresholds_for_language(self, language: str | None) -> LanguageThresholds:
        """Return the thresholds to use for the given language.

        Falls back to the document-wide ``self.min_chars`` /
        ``self.min_confidence`` when adaptive thresholds are
        disabled or no language has been detected.
        """
        if not settings.ocr_cascading_use_adaptive_thresholds or not language:
            return LanguageThresholds(
                min_chars=self.min_chars,
                min_confidence=self.min_confidence,
            )
        thresholds = thresholds_for(language)
        track_ocr_language_threshold_used(language, "min_chars")
        track_ocr_language_threshold_used(language, "min_confidence")
        return thresholds

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


__all__ = ["CascadingOCREngine", "_quality", "_should_replace_with_fallback"]
