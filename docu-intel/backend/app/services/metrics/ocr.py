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

from prometheus_client import Counter

from ._registry import (
    DOCLING_DURATION,
    DOCLING_FALLBACK,
    DOCLING_PAGES,
    DOCLING_REQUESTS,
    OCR_CASCADE_FALLBACK,
    OCR_DPI_ESCALATION,
    OCR_DURATION,
    OCR_LANGUAGE_DETECTED,
    OCR_LANGUAGE_THRESHOLD_USED,
    OCR_POSTPROCESS_CORRECTIONS,
    OCR_RENDER_PERMISSION_FAILURES,
    OCR_SKIP_TIER2,
    OCR_TIER4_INVOKED,
    OCR_TIER_AVAILABLE,
    OCR_TIER_BY_DOC_TYPE,
    OCR_TIER_USED,
    OVISOCR2_DURATION,
    OVISOCR2_OUTPUT_FEATURES,
    OVISOCR2_REQUESTS,
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


# Allow-list of Tier 4 invocation reasons. Anything outside this set
# buckets under ``"other"`` so the cardinality stays bounded (the
# reason is set by the cascade in two well-defined places today; new
# callers must add their reason here).
_TIER4_REASONS = frozenset({"under_threshold", "circuit_open", "explicit_call", "canary"})


def track_ocr_tier4_invoked(reason: str) -> None:
    """Record that the cascade consulted Tier 4 (VLM) for a page.

    M1 (Sprint 3): Tier 4 is expensive (an HTTP round-trip to the
    VLM endpoint, ~1-3 s, plus the image payload in base64), and
    it only fires when the best Tier 1-3 result is below
    ``tier4_quality_threshold``. Tracking the *reason* tells the
    operator whether Tier 4 is being invoked because the rest of
    the cascade is genuinely weak (the bad case, indicates that
    the previous tiers are degrading) or because the breaker is
    open (the recovery case — Tier 4 was tried, then the breaker
    tripped and the cascade fell back to Tier 1-3 for the next
    page).
    """
    clean = (reason or "unknown").lower().strip() or "unknown"
    if clean not in _TIER4_REASONS:
        clean = "other"
    OCR_TIER4_INVOKED.labels(reason=clean).inc()


_OVISOCR2_OUTCOMES = frozenset({"success", "failure", "circuit_open", "not_eligible"})
_OVISOCR2_REASONS = frozenset(
    {
        "stable_canary",
        "tier4_primary",
        "complex_route",
        "empty_or_missing_ocr",
        "low_ocr_confidence",
        "table_structure",
        "formula_structure",
        "filename_complexity_hint",
        "quality_control",
        "native_control",
        "unknown",
    }
)
_OVISOCR2_FEATURES = frozenset(
    {"text", "table", "formula", "figure", "truncated", "repetitive", "empty", "invalid_region"}
)


def track_ovisocr2_request(outcome: str, reason: str, duration: float | None = None) -> None:
    """Track a single OvisOCR2 request without document-specific labels."""
    clean_outcome = (outcome or "unknown").lower().strip()
    if clean_outcome not in _OVISOCR2_OUTCOMES:
        clean_outcome = "failure"
    clean_reason = (reason or "unknown").lower().strip().split(":", 1)[0]
    if clean_reason not in _OVISOCR2_REASONS:
        clean_reason = "unknown"
    OVISOCR2_REQUESTS.labels(outcome=clean_outcome, reason=clean_reason).inc()
    if duration is not None and duration >= 0:
        OVISOCR2_DURATION.labels(outcome=clean_outcome).observe(duration)


def track_ovisocr2_output_feature(feature: str) -> None:
    clean = (feature or "unknown").lower().strip()
    if clean not in _OVISOCR2_FEATURES:
        return
    OVISOCR2_OUTPUT_FEATURES.labels(feature=clean).inc()


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


# Preprocessing metrics
PREPROCESS_PATH_CHOSEN = Counter(
    "ocr_preprocess_path_chosen_total",
    "Preprocessing path chosen (scan, manuscript, photo_skip)",
    ["path_type"],
)


def track_preprocess_path_chosen(path_type: str) -> None:
    """Record which preprocessing path was chosen for an image.

    ``path_type`` is one of ``"scan"``, ``"manuscript"``, ``"photo_skip"``.
    """
    PREPROCESS_PATH_CHOSEN.labels(
        path_type=(path_type or "unknown").lower().strip() or "unknown",
    ).inc()


# ---------------------------------------------------------------------------
# CR9 — OCR render permission & tier availability
# ---------------------------------------------------------------------------


def track_ocr_render_permission_failure() -> None:
    """Record a permission denied error when rendering a page for OCR."""
    OCR_RENDER_PERMISSION_FAILURES.inc()


def set_ocr_tier_available(tier: str, available: bool) -> None:
    """Set the availability gauge for a given OCR tier.

    ``tier`` is one of ``"tesseract" | "paddleocr" | "pp_structure" | "vlm"``.
    """
    clean_tier = (tier or "unknown").lower().strip() or "unknown"
    OCR_TIER_AVAILABLE.labels(tier=clean_tier).set(1.0 if available else 0.0)


# ---------------------------------------------------------------------------
# Docling PDF parser — bounded outcome vocabulary that mirrors OvisOCR2.
# ---------------------------------------------------------------------------
_DOCLING_OUTCOMES = frozenset({"success", "failure", "timeout", "circuit_open"})
_DOCLING_FALLBACK_REASONS = frozenset(
    {
        "not_configured",
        "not_eligible",
        "circuit_open",
        "timeout",
        "failure",
        "exception",
        "non_pdf",
    }
)
_DOCLING_PAGE_KINDS = frozenset({"digital", "scanned"})


def track_docling_request(outcome: str, reason: str, duration: float | None = None) -> None:
    """Record a single Docling request without document-specific labels.

    ``outcome`` is the bounded enum above; anything else buckets under
    ``"failure"`` so a typo in the caller cannot explode the label
    cardinality. ``reason`` is a free-form string the operator can use
    for debugging (URL, exception class, …) and is truncated to 64
    characters so a chatty exception message cannot either.
    """
    clean_outcome = (outcome or "unknown").lower().strip()
    if clean_outcome not in _DOCLING_OUTCOMES:
        clean_outcome = "failure"
    clean_reason = (reason or "n/a").lower().strip()[:64] or "n/a"
    DOCLING_REQUESTS.labels(outcome=clean_outcome, reason=clean_reason).inc()
    if duration is not None and duration >= 0:
        DOCLING_DURATION.labels(outcome=clean_outcome).observe(duration)


def track_docling_pages(*, digital: int, scanned: int) -> None:
    """Record the per-request digital/scanned page split.

    Counters are incremented (not set) so a request that sees 5
    digital + 2 scanned pages contributes ``+5`` to ``digital`` and
    ``+2`` to ``scanned``. The split is intentionally a separate
    counter from the request outcome: it lets the operator see
    "Docling returned a successful request that was 80% scanned"
    without having to dissect the JSON payload.
    """
    if digital > 0:
        DOCLING_PAGES.labels(kind="digital").inc(digital)
    if scanned > 0:
        DOCLING_PAGES.labels(kind="scanned").inc(scanned)


def track_docling_fallback(reason: str) -> None:
    """Record that the parser router fell back from Docling to legacy.

    The label set is the bounded enum above; a free-form reason is
    intentionally not accepted to keep the cardinality predictable.
    The reason ``"non_pdf"`` is reserved for the router short-circuit
    (a non-PDF extension that should never have reached Docling in
    the first place — useful for spotting a future regression in the
    router dispatch order).
    """
    clean = (reason or "unknown").lower().strip()
    if clean not in _DOCLING_FALLBACK_REASONS:
        clean = "failure"
    DOCLING_FALLBACK.labels(reason=clean).inc()
