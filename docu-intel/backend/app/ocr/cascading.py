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
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine, OCRResult
from app.ocr.preprocess import clear_preprocess_cache
from app.services.metrics import (
    track_ocr_cascade_fallback,
    track_ocr_duration,
    track_ocr_language_threshold_used,
    track_ocr_skip_tier2,
    track_ocr_tier4_invoked,
    track_ocr_tier_used,
)
from app.services.ocr_language import LanguageThresholds, thresholds_for

logger = logging.getLogger("app.ocr.cascading")
QUALITY_EPSILON = 0.01
# Tier 4 (VLM-OCR) es menos fiable: exige mejora más clara
TIER4_QUALITY_DELTA = 0.15


def _quality(result: OCRResult) -> float:
    text = (result.text or "").strip()
    if not text:
        return 0.0
    alnum = _alnum_count(text)
    density = alnum / max(len(text), 1)
    # confidence=None → 0.5 es un neutral deliberado, no un bug
    conf = result.confidence if result.confidence is not None else 0.5
    conf = max(0.0, min(1.0, conf))
    length_factor = min(len(text) / 500.0, 1.0)
    # densidad es la señal más fiable entre motores heterogéneos
    return conf * 0.4 + density * 0.4 + length_factor * 0.2


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
        tier4_fallback: BaseOCREngine | None = None,
        tier4_quality_threshold: float = 0.62,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.pp_structure = pp_structure
        self.vlm_ocr = vlm_ocr
        self.tier4_fallback = tier4_fallback
        self.min_chars = min_chars
        self.min_confidence = min_confidence
        self.tier4_quality_threshold = tier4_quality_threshold
        # O2 — per-page language context. The parser sets this before
        # each ``extract`` call; the cascade reads it to look up the
        # per-language thresholds. ``None`` means "no detection, use
        # the legacy document-wide constants".
        #
        # Page-parallel processing: the language is stored thread-locally
        # so two pages being OCR'd in parallel each carry their own
        # language without racing on a shared attribute. The existing
        # ``engine.current_language = "es"`` assignment API keeps working
        # through the property setter.
        self._tls = threading.local()
        self._tls.language: str | None = None
        # ``name`` is the engine identity of the last result; default to
        # the primary so a query before any call still has a sensible
        # value. Stored in thread-local to avoid race conditions when
        # ocr_page_parallelism > 1.
        self._tls.name: str = primary.name

    @property
    def name(self) -> str:
        return getattr(self._tls, "name", self.primary.name)

    @property
    def current_language(self) -> str | None:
        return getattr(self._tls, "language", None)

    @current_language.setter
    def current_language(self, value: str | None) -> None:
        self._tls.language = value

    def extract(self, image_path: Path) -> OCRResult:
        # O1: clear the preprocessing cache so each page starts fresh.
        clear_preprocess_cache()

        # Photo detection: for product photos, try OCR first but fall back
        # to vision LLM if OCR fails. This ensures handwritten text and
        # sketches are not skipped entirely.
        is_photo = False
        try:
            from app.parsers.clip_classifier import classify_image

            clip_result = classify_image(image_path)
            if (
                clip_result["category"] == "product_photo"
                and clip_result["confidence"] > 0.75
            ):
                is_photo = True
                logger.info("Photo detected, will try OCR then vision: %s", image_path.name)
        except Exception:
            logger.debug("photo classification skipped: %s", image_path.name)

        start = time.perf_counter()
        primary_result = self.primary.extract(image_path)
        track_ocr_duration(time.perf_counter() - start)

        # For photos, if OCR produces little text, try vision LLM directly
        if is_photo and self.vlm_ocr is not None:
            primary_text = (primary_result.text or "").strip()
            if len(primary_text) < 50:  # OCR produced very little text
                logger.info("Photo OCR insufficient (%d chars), trying vision LLM", len(primary_text))
                try:
                    vision_result = self.vlm_ocr.extract(image_path)
                    if _quality(vision_result) > _quality(primary_result) + QUALITY_EPSILON:
                        return self._finalize(image_path, "vision", vision_result)
                except Exception as exc:
                    logger.warning("Vision LLM failed for photo: %s", exc)

        if self._is_acceptable(primary_result):
            return self._finalize(image_path, self.primary.name, primary_result)

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
            return self._finalize(image_path, self.primary.name, primary_result)
        track_ocr_duration(time.perf_counter() - start)

        should_replace, reason = _should_replace_with_fallback(primary_result, fallback_result)
        if should_replace:
            # Tier 2 won — try Tier 3 only if it's wired in AND Tier 2
            # is still weak (below thresholds). Otherwise return Tier 2.
            if self.pp_structure is not None and not self._is_acceptable(fallback_result):
                tier3 = self._try_tier3(image_path, primary_result, fallback_result)
                if tier3 is not None:
                    return self._finalize(
                        image_path,
                        self.pp_structure.name if self.pp_structure else self.name,
                        tier3,
                    )
            return self._finalize(image_path, self.fallback.name, fallback_result)

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
            tier3 = self._try_tier3(image_path, primary_result, fallback_result)
            if tier3 is not None:
                return self._finalize(image_path, self.pp_structure.name, tier3)

        return self._finalize(image_path, self.primary.name, primary_result)

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
        if self.pp_structure is None:  # caller-guaranteed (see __init__)
            raise RuntimeError("PP-Structure engine not initialised")
        start = time.perf_counter()
        try:
            tier3_result = self.pp_structure.extract(image_path)
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.pp_structure.name, exc)
            return None
        track_ocr_duration(time.perf_counter() - start)

        # PP-Structure is judged on quality, not text length.
        # A result with short but clean text and high confidence should
        # not be discarded just because it's below min_chars.
        if not tier3_result.text or _quality(tier3_result) <= QUALITY_EPSILON:
            return None

        best_prior = (
            fallback_result if self._is_better(fallback_result, primary_result) else primary_result
        )
        if self._is_better(tier3_result, best_prior):
            return tier3_result
        return None

    def _finalize(self, image_path: Path, tier: str, result: OCRResult) -> OCRResult:
        if self.vlm_ocr is None or _quality(result) >= self.tier4_quality_threshold:
            return self._record_winner(tier, result)
        # M1: Tier 4 was consulted because the best Tier 1-3 result
        # is below the configured quality threshold. Track this so the
        # operator can see how often Tier 4 fires and from which
        # reasons (under-threshold vs. circuit_open vs. explicit).
        track_ocr_tier4_invoked("under_threshold")
        tier4_result = self._try_tier4(image_path, result)
        if tier4_result is not None:
            return tier4_result
        return self._record_winner(tier, result)

    def _try_tier4(self, image_path: Path, best_prior: OCRResult) -> OCRResult | None:
        if self.vlm_ocr is None:  # caller-guaranteed (see __init__)
            raise RuntimeError("VLM OCR engine not initialised")
        start = time.perf_counter()
        try:
            logger.info("OCR Tier 4 sending page to %s: image=%s", self.vlm_ocr.name, image_path.name)
            tier4_result = self.vlm_ocr.extract(image_path)
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.vlm_ocr.name, exc)
            if self.tier4_fallback is None:
                return None
            return self._try_tier4_fallback(image_path, best_prior, self.tier4_fallback)
        track_ocr_duration(time.perf_counter() - start)

        if _quality(tier4_result) > _quality(best_prior) + TIER4_QUALITY_DELTA:
            return self._record_winner(self.vlm_ocr.name, tier4_result)
        return None

    def _try_tier4_fallback(
        self,
        image_path: Path,
        best_prior: OCRResult,
        engine: BaseOCREngine,
    ) -> OCRResult | None:
        start = time.perf_counter()
        try:
            logger.info("OCR Tier 4 fallback sending page to %s: image=%s", engine.name, image_path.name)
            tier4_result = engine.extract(image_path)
        except Exception as exc:
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(engine.name, exc)
            return None
        track_ocr_duration(time.perf_counter() - start)
        if _quality(tier4_result) > _quality(best_prior) + TIER4_QUALITY_DELTA:
            logger.info("OCR Tier 4 fallback used: engine=%s image=%s", engine.name, image_path.name)
            return self._record_winner(engine.name, tier4_result)
        return None

    def _is_acceptable(self, result: OCRResult) -> bool:
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
        thresholds = self._thresholds_for_current_page()
        if not result.text or len(result.text.strip()) < thresholds.min_chars:
            return False
        # Unknown confidence (None) should not bypass the quality gate.
        # Fall back to a text-length check when confidence is missing.
        if result.confidence is None:
            return len(result.text.strip()) >= thresholds.min_chars
        return result.confidence >= thresholds.min_confidence

    def _thresholds_for_current_page(self) -> LanguageThresholds:
        """Return the thresholds to use for the current page.

        Falls back to the document-wide ``self.min_chars`` /
        ``self.min_confidence`` when adaptive thresholds are
        disabled or no language has been detected.
        """
        if not settings.ocr_cascading_use_adaptive_thresholds or not self.current_language:
            return LanguageThresholds(
                min_chars=self.min_chars,
                min_confidence=self.min_confidence,
            )
        thresholds = thresholds_for(self.current_language)
        track_ocr_language_threshold_used(self.current_language, "min_chars")
        track_ocr_language_threshold_used(self.current_language, "min_confidence")
        return thresholds

    def _is_better(self, candidate: OCRResult, baseline: OCRResult) -> bool:
        """Decide whether the fallback result should replace the primary.

        The candidate must beat the baseline on quality by a small margin.
        Length is only one saturated component of the score, so noisy OCR
        cannot win just by emitting more characters.
        """
        return _quality(candidate) > _quality(baseline) + QUALITY_EPSILON

    def extract_batch(
        self, image_paths: list[Path], max_workers: int = 4
    ) -> list[OCRResult]:
        """Process multiple pages in parallel using ThreadPoolExecutor.

        Tesseract is stateless per page, so parallel processing is safe.
        GPU engines (PaddleOCR, PP-Structure) use their own internal locks.

        Args:
            image_paths: List of page image paths to process.
            max_workers: Max parallel threads (default 4, matches CPU cores
                         for Tesseract; GPU engines serialize internally).

        Returns:
            List of OCRResults in the same order as image_paths.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if len(image_paths) <= 1:
            return [self.extract(image_paths[0])] if image_paths else []

        results: list[OCRResult | None] = [None] * len(image_paths)
        path_to_idx = {path: idx for idx, path in enumerate(image_paths)}

        logger.info(
            "OCR batch: processing %d pages with %d workers",
            len(image_paths),
            max_workers,
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self.extract, path): path for path in image_paths
            }
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                idx = path_to_idx[path]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    logger.error("OCR batch: page %s failed: %s", path.name, exc)
                    results[idx] = OCRResult(
                        text="", confidence=None, blocks=[], engine=self.name
                    )

        return results  # type: ignore[return-value]

    def _record_winner(self, tier: str, result: OCRResult) -> OCRResult:
        self._tls.name = tier
        track_ocr_tier_used(tier)
        return result

    def _track_fallback_failure(self, engine_name: str, exc: Exception) -> None:
        reason = str(exc) or exc.__class__.__name__
        logger.warning("OCR cascade engine %s failed: %s", engine_name, reason)
        track_ocr_cascade_fallback(engine_name, reason)


__all__ = ["CascadingOCREngine", "_quality", "_should_replace_with_fallback", "TIER4_QUALITY_DELTA"]
