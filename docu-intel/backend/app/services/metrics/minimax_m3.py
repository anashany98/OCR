"""MiniMax M3 — extraction fingerprint and classification instrumentation.

This module is the single entry point for the FASE 2 / FASE 3 metrics.
The functions are intentionally tiny: each one maps a bounded label
set to a Prometheus counter or histogram defined in ``_registry``.

The module also exposes :class:`ExtractionFingerprintTimer`, a context
manager that records the wall-clock duration of one extraction attempt
and tags it with the route, outcome and size class without exposing
the document hash, filename or any other high-cardinality value.
"""

from __future__ import annotations

import time
from typing import Literal

from ._registry import (
    CLASSIFICATION_LAYER,
    CLASSIFICATION_RECLASSIFY,
    EXTRACTION_FINGERPRINT_DURATION,
    EXTRACTION_FINGERPRINT_RESULT,
    EXTRACTION_FINGERPRINT_REUSED,
)

RouteLabel = Literal["deterministic", "llm_text", "vlm"]
OutcomeLabel = Literal[
    "success",
    "invalid_json",
    "repaired",
    "timeout",
    "provider_error",
    "skipped",
    "cache_hit",
    "error",
]
SizeClassLabel = Literal["small", "medium", "large"]


def _bucket_size(*, chars: int) -> SizeClassLabel:
    """Bucket a document's text length into a bounded size class.

    The class boundaries are the same ones used by
    :func:`document_processing_core.classify_size_class`, kept
    consistent so the histogram and the gauge line up.
    """
    if chars <= 0:
        return "small"
    if chars < 6_000:
        return "small"
    if chars < 24_000:
        return "medium"
    return "large"


class ExtractionFingerprintTimer:
    """Context manager that records one extraction attempt.

    Usage::

        with ExtractionFingerprintTimer(route="llm_text", chars=len(text)) as t:
            try:
                fields = call_provider(...)
                t.set_outcome("success" if fields else "empty")
            except TimeoutError:
                t.set_outcome("timeout")
                raise
    """

    def __init__(self, *, route: RouteLabel, chars: int) -> None:
        self.route = route
        self.size_class = _bucket_size(chars=chars)
        self.outcome: OutcomeLabel = "error"
        self._t0: float = 0.0
        self._recorded = False

    def set_outcome(self, outcome: OutcomeLabel) -> None:
        self.outcome = outcome

    def __enter__(self) -> ExtractionFingerprintTimer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._recorded:
            return
        self._recorded = True
        elapsed = max(time.perf_counter() - self._t0, 0.0)
        if exc is not None:
            self.outcome = "error"
        try:
            EXTRACTION_FINGERPRINT_DURATION.labels(route=self.route, outcome=self.outcome).observe(
                elapsed
            )
            EXTRACTION_FINGERPRINT_RESULT.labels(
                route=self.route,
                outcome=self.outcome,
                size_class=self.size_class,
            ).inc()
        except Exception:  # pragma: no cover - metrics must never raise
            pass


def track_extraction_reused(*, route: RouteLabel) -> None:
    """Record that an extraction was skipped because the fingerprint
    matched a prior valid result."""
    EXTRACTION_FINGERPRINT_REUSED.labels(route=route).inc()


ClassificationDimension = Literal["source_format", "document_type", "subtype", "tags"]
ClassificationPath = Literal[
    "source_format",
    "filename",
    "parser",
    "learned",
    "rules",
    "llm",
    "manual",
    "fallback",
]


def track_classification_layer(
    *,
    dimension: ClassificationDimension,
    path: ClassificationPath,
    size_class: SizeClassLabel,
) -> None:
    """Record which layer produced the final label for a given
    classification dimension. ``size_class`` is the same bucket used
    for the extraction timer so an operator can correlate."""
    CLASSIFICATION_LAYER.labels(
        dimension=dimension,
        path=path,
        size_class=size_class,
    ).inc()


def track_classification_reclassify(
    *,
    relaunched_ocr: bool,
    relaunched_extraction: bool,
) -> None:
    """Record a reclassification attempt and whether it kicked off
    new OCR or extraction work. The target of FASE 2.5 is that
    reclassification never relaunches these stages."""
    CLASSIFICATION_RECLASSIFY.labels(
        relauched_ocr="true" if relaunched_ocr else "false",
        relauched_extraction="true" if relaunched_extraction else "false",
    ).inc()
