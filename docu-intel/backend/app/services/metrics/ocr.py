"""OCR-specific metrics: durations, tier used, DPI escalation, language.

The functions in this module are the ``track_*`` entry points the
rest of the codebase calls. They keep the API identical to the
original ``services/metrics.py`` so callers do not have to change.

Each function:

1. Validates the inputs (lowercase, strip, default to ``"unknown"``).
2. Bounded-label sanitisation: we keep the label cardinality
   under control by bucketing or by trimming at the call site.
3. Forwards the increment to the matching ``prometheus_client``
   Counter or Histogram.

Why a separate module
--------------------
OCR is the largest single source of metrics in the platform
(per-tier, per-language, per-document-type, per-DPI). Keeping the
``track_*`` functions next to the metric definitions makes the
labels easier to keep in sync and gives reviewers a single file
to audit when changing the cascade.
"""
from __future__ import annotations

from ._registry import (
    OCR_CASCADE_FALLBACK,
    OCR_DPI_ESCALATION,
    OCR_DURATION,
    OCR_LANGUAGE_DETECTED,
    OCR_LANGUAGE_THRESHOLD_USED,
    OCR_POSTPROCESS_CORRECTIONS,
    OCR_SKIP_TIER2,
    OCR_TIER_BY_DOC_TYPE,
    OCR_TIER_USED,
)
from .labels import escape_label


# Allow-list of language codes we accept on the Prometheus label
# side. Anything else buckets under ``"unknown"`` so the cardinality
# cannot explode when the parser runs on a noisy 200-page PDF.
_ALLOWED_LANGUAGES = frozenset({"es", "en", "ca", "fr", "de", "it", "pt", "gl", "eu", "va"})


def _normalise_language(language: str | None) -> str:
    clean = (language or "unknown").lower().strip()
    if not clean:
        return "unknown"
    if clean in _ALLOWED_LANGUAGES:
        return clean
    return "unknown"


def _normalise_doc_type(document_type: str | None) -> str:
    clean = (document_type or "unknown").lower().strip()
    return clean or "unknown"


def track_ocr_duration(
    duration: float,
    *,
    tier: str | None = None,
    language: str | None = None,
) -> None:
    """Record the wall-clock duration of one OCR request.

    ``tier`` and ``language`` are the optional labels that drive
    the per-tier / per-language breakdown. They are best-effort:
    the caller may not know them at the point of recording.
    """
    OCR_DURATION.labels(
        tier=(tier or "unknown").lower().strip() or "unknown",
        language=_normalise_language(language),
    ).observe(duration)


def track_ocr_cascade_fallback(engine_name: str, reason: str) -> None:
    """Record that the OCR cascade fell back to a lower tier.

    ``engine_name`` and ``reason`` are the two labels. Both are
    short, bounded strings (the cascade names each tier once at
    startup, and the reasons are a short enum), so the
    cardinality is small.
    """
    OCR_CASCADE_FALLBACK.labels(
        engine=escape_label((engine_name or "unknown").lower().strip() or "unknown"),
        reason=escape_label((reason or "unknown").lower().strip() or "unknown"),
    ).inc()


def track_ocr_dpi_escalation(*, from_dpi: int, to_dpi: int) -> None:
    """Record that the OCR DPI ladder escalated from one DPI to
    another because Tier 1 produced a weak result.

    ``from_dpi`` and ``to_dpi`` are the DPI values before and
    after the re-render (e.g. 300 and 400). The label set is
    bounded: only 2 transitions are possible (300->400 and
    400->600).
    """
    OCR_DPI_ESCALATION.labels(from_dpi=str(from_dpi), to_dpi=str(to_dpi)).inc()


def track_ocr_postprocess(*, correction_count: int) -> None:
    """Record the number of corrections applied by the OCR
    post-processor to a single page. The running total is
    exposed as a Prometheus counter."""
    if correction_count <= 0:
        return
    OCR_POSTPROCESS_CORRECTIONS.inc(correction_count)


def track_ocr_tier_used(tier: str, document_type: str | None = None) -> None:
    """Record which tier won the cascade for a page.

    ``tier`` is one of ``"tesseract" | "paddleocr" | "pp_structure" |
    "dots_mocr"``. ``document_type`` is the document's class
    (``"presupuesto" | "factura" | ...``); when ``None`` the
    per-document-type counter is not incremented, but the
    overall tier counter still is.
    """
    clean_tier = (tier or "unknown").lower().strip() or "unknown"
    OCR_TIER_USED.labels(tier=clean_tier).inc()
    if document_type:
        clean_doc = _normalise_doc_type(document_type)
        OCR_TIER_BY_DOC_TYPE.labels(tier=clean_tier, document_type=clean_doc).inc()


def track_ocr_skip_tier2(reason: str) -> None:
    """Record that the cascade kept the primary result instead of
    replacing it with the Tier 2 fallback.

    ``reason`` is a short label such as
    ``"no_significant_gain"``, ``"both_weak"`` or
    ``"alnum_below_threshold"``.
    """
    clean = (reason or "unknown").lower().strip() or "unknown"
    OCR_SKIP_TIER2.labels(reason=clean).inc()


def track_ocr_language_detected(language: str, document_type: str) -> None:
    """Record the language the parser detected for a page.

    ``language`` is the ISO-639-1 code (or ``"unknown"``). The
    allow-list keeps the cardinality bounded.
    """
    OCR_LANGUAGE_DETECTED.labels(
        language=_normalise_language(language),
        document_type=_normalise_doc_type(document_type),
    ).inc()


def track_ocr_language_threshold_used(language: str, threshold_type: str) -> None:
    """Record which per-language threshold the cascade consulted.

    ``threshold_type`` is one of ``"min_chars"`` or
    ``"min_confidence"``.
    """
    OCR_LANGUAGE_THRESHOLD_USED.labels(
        language=_normalise_language(language),
        threshold_type=(threshold_type or "unknown").lower().strip() or "unknown",
    ).inc()
