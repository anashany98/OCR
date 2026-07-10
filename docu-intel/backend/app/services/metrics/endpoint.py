"""Render the /metrics endpoint and (optionally) the legacy flat dict.

Two surfaces live here:

1. ``render_metrics(db, queue_status)`` — the new Prometheus
   exposition. Uses :func:`prometheus_client.generate_latest`
   over the default global ``REGISTRY`` plus a couple of
   computed gauges (cache hit rate, document status counts).
2. ``get_metrics()`` — the legacy flat dict used by the admin
   UI. Kept so the rest of the codebase that imports
   ``metrics.get_metrics()`` keeps working.

Why both surfaces
-----------------
The admin UI was wired against the flat dict and there is no
time to migrate it to scraping Prometheus. We serve both: the
operator's Prometheus job can scrape ``/metrics`` (new
format) and the admin UI can call ``get_metrics()`` to render
counters directly (legacy format).
"""

from __future__ import annotations

from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY
from prometheus_client.exposition import generate_latest as _gen
from fastapi import Header, HTTPException
from starlette.responses import Response

from app.core.config import settings

from .labels import escape_label, metric_key
from .pipeline import (
    document_status_counts,
    refresh_documents_by_status_gauge,
    update_queue_status_snapshot,
)
from .search import update_cache_hit_rate

# ---------------------------------------------------------------------------
# Legacy flat-dict output (for the admin UI)
# ---------------------------------------------------------------------------


def get_metrics() -> dict[str, float]:
    """Return a flat ``{key: value}`` dict for the admin UI.

    The admin UI is not Prometheus-aware. Instead of ripping the
    UI out, we keep the flat output around and reconstruct it
    on demand from the current Counter / Gauge values. The keys
    match the legacy format so the UI's existing column layout
    keeps working.
    """
    from ._registry import (
        CACHE_HITS,
        CACHE_MISSES,
        DOCUMENTS_BY_STATUS,
        DOCUMENTS_FAILED,
        DOCUMENTS_PROCESSED,
        EMBEDDING_FALLBACKS,
        FEEDBACK_VOTES,
        JOBS_PENDING_BY_QUEUE,
        MMR_AVG_PAIRWISE_SIMILARITY,
        MMR_OUTCOMES,
        OCR_CASCADE_FALLBACK,
        OCR_DPI_ESCALATION,
        OCR_LANGUAGE_DETECTED,
        OCR_LANGUAGE_THRESHOLD_USED,
        OCR_POSTPROCESS_CORRECTIONS,
        OCR_SKIP_TIER2,
        OCR_TIER_BY_DOC_TYPE,
        OCR_TIER_USED,
        PROMPT_INJECTION_ATTEMPTS,
        QUERY_TRANSFORM,
        WATCHER_ERRORS,
    )

    def _c(counter) -> float:
        return float(counter._value.get())

    def _g(gauge) -> float:
        return float(gauge._value.get())

    data: dict[str, float] = {}

    # Documents.
    data["documents_processed"] = _c(DOCUMENTS_PROCESSED)
    data["documents_failed"] = _c(DOCUMENTS_FAILED)
    for status, gauge in DOCUMENTS_BY_STATUS._metrics.items():
        data[f"documents_by_status_{metric_key(status)}"] = _g(gauge)

    # Cache.
    data["cache_hits"] = _c(CACHE_HITS)
    data["cache_misses"] = _c(CACHE_MISSES)
    total_cache = data["cache_hits"] + data["cache_misses"]
    if total_cache > 0:
        data["cache_hit_rate"] = data["cache_hits"] / total_cache

    # Embedding.
    data["embedding_fallbacks"] = _c(EMBEDDING_FALLBACKS)

    # Watcher.
    data["watcher_errors"] = _c(WATCHER_ERRORS)

    # Queues.
    for queue, gauge in JOBS_PENDING_BY_QUEUE._metrics.items():
        data[f"jobs_pending_{metric_key(queue)}"] = _g(gauge)

    # OCR.
    for (engine, reason), counter in OCR_CASCADE_FALLBACK._metrics.items():
        data[f"ocr_cascade_fallback_total_{metric_key(engine)}_{metric_key(reason)}"] = _c(counter)
    for (tier,), counter in OCR_TIER_USED._metrics.items():
        data[f"ocr_tier_used_total_{metric_key(tier)}"] = _c(counter)
    for (tier, doc_type), counter in OCR_TIER_BY_DOC_TYPE._metrics.items():
        data[f"ocr_tier_by_doc_type_{metric_key(tier)}_{metric_key(doc_type)}"] = _c(counter)
    for (from_dpi, to_dpi), counter in OCR_DPI_ESCALATION._metrics.items():
        data[f"ocr_dpi_escalation_total_{from_dpi}_to_{to_dpi}"] = _c(counter)
    data["ocr_postprocess_corrections_total"] = _c(OCR_POSTPROCESS_CORRECTIONS)
    for (reason,), counter in OCR_SKIP_TIER2._metrics.items():
        data[f"ocr_skip_tier2_total_{metric_key(reason)}"] = _c(counter)
    for (lang, doc_type), counter in OCR_LANGUAGE_DETECTED._metrics.items():
        data[f"ocr_language_detected_total_{metric_key(lang)}_{metric_key(doc_type)}"] = _c(counter)
    for (lang, threshold_type), counter in OCR_LANGUAGE_THRESHOLD_USED._metrics.items():
        data[f"ocr_language_threshold_used_{metric_key(lang)}_{metric_key(threshold_type)}"] = _c(
            counter
        )

    # Search.
    for (strategy, outcome), counter in QUERY_TRANSFORM._metrics.items():
        data[f"query_transform_{metric_key(strategy)}_{metric_key(outcome)}"] = _c(counter)
    for (outcome,), counter in MMR_OUTCOMES._metrics.items():
        data[f"mmr_total_{metric_key(outcome)}"] = _c(counter)
    for (outcome,), gauge in MMR_AVG_PAIRWISE_SIMILARITY._metrics.items():
        data[f"mmr_avg_pairwise_similarity_{metric_key(outcome)}"] = _g(gauge)
    for (action, sensitivity, bucket), counter in PROMPT_INJECTION_ATTEMPTS._metrics.items():
        data[
            f"prompt_injection_attempts_{metric_key(action)}_{metric_key(sensitivity)}_{metric_key(bucket)}"
        ] = _c(counter)
    for (vote, reason), counter in FEEDBACK_VOTES._metrics.items():
        data[f"feedback_votes_{metric_key(vote)}_{metric_key(reason)}"] = _c(counter)

    return data


# ---------------------------------------------------------------------------
# Prometheus exposition (the new path)
# ---------------------------------------------------------------------------


def render_metrics(
    db: Any = None,
    queue_status: Any = None,
) -> bytes:
    """Return the current state of every Prometheus metric in the
    default :data:`REGISTRY`, formatted for the standard
    ``/metrics`` endpoint.

    ``db`` is optional: when provided, the document-status
    gauge is refreshed from the database before the render.
    ``queue_status`` is the same optional Celery snapshot used
    by the legacy path.
    """
    # 1. Refresh the derived gauges so the scrape picks up the
    #    latest values.
    if queue_status is not None:
        update_queue_status_snapshot(queue_status)
    if db is not None:
        refresh_documents_by_status_gauge(db)
    update_cache_hit_rate()

    # 2. Let ``prometheus_client`` format the whole registry.
    #    We do not need to touch any specific counter: every
    #    ``prometheus_client`` metric registered with the default
    #    ``REGISTRY`` is rendered by ``generate_latest``.
    return _gen(REGISTRY)


# ---------------------------------------------------------------------------
# FastAPI route
# ---------------------------------------------------------------------------


def register_metrics_endpoint(app) -> None:
    """Mount the ``/metrics`` endpoint on ``app``.

    Mirrors the original ``services/metrics.py`` shape so the
    rest of the codebase (``app/main.py``) keeps working.
    """

    @app.get("/metrics")
    def metrics(
        x_metrics_token: str | None = Header(default=None, alias="X-Metrics-Token"),
    ) -> Response:
        is_local = settings.environment in {"local", "development", "test"}
        token_required = not is_local or bool(settings.metrics_token)
        if token_required and x_metrics_token != settings.metrics_token:
            raise HTTPException(status_code=401, detail="metrics token required")
        return Response(
            content=render_metrics(),
            media_type=CONTENT_TYPE_LATEST,
        )


__all__ = [
    "render_metrics",
    "get_metrics",
    "register_metrics_endpoint",
    "CONTENT_TYPE_LATEST",
    "escape_label",
    "metric_key",
    "document_status_counts",
    "update_queue_status_snapshot",
    "refresh_documents_by_status_gauge",
]
