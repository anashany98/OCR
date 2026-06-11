"""Prometheus metrics for the Docu-Intel platform.

This package was previously a single 700-line ``services/metrics.py``
file that hand-wrote the OpenMetrics exposition format. It now
follows the standard ``prometheus_client`` patterns (Counter,
Histogram, Gauge) and is split by concern:

  ``ocr``        OCR durations, tier usage, DPI escalation,
                 language detection, cascade fallback.
  ``embedding``  Embedding latency + fallback counter.
  ``search``     Search latency, strategy used, cache hit rate.
  ``pipeline``   Documents processed/failed, watcher errors,
                 queue status, DB-sourced per-status counts.
  ``rag``        Query transformer, MMR, prompt-injection
                 attempts, feedback loop, chunk weights.
  ``endpoint``   ``/metrics`` route + ``render_metrics()`` +
                 the legacy ``get_metrics()`` flat dict.
  ``_registry``  The actual ``prometheus_client`` Counter /
                 Histogram / Gauge definitions.
  ``labels``     Label escaping helpers.

Public API
----------
The functions below are what the rest of the codebase calls.
They are re-exported from this ``__init__`` so ``from
app.services.metrics import track_ocr_duration`` still works
(legacy import shape).
"""
from __future__ import annotations

# Re-export the public surface. The original ``services/metrics.py``
# exposed these names; we keep them importable from
# ``app.services.metrics`` (the package) so no caller has to
# change anything.
from .ocr import (
    track_ocr_cascade_fallback,
    track_ocr_dpi_escalation,
    track_ocr_duration,
    track_ocr_language_detected,
    track_ocr_language_threshold_used,
    track_ocr_postprocess,
    track_ocr_skip_tier2,
    track_ocr_tier_used,
)
from .embedding import (
    track_embedding_duration,
    track_embedding_fallback,
    track_embedding_latency,
)
from .search import (
    track_cache_hit,
    track_cache_miss,
    track_search_latency,
    track_search_strategy_used,
    update_cache_hit_rate,
)
from .pipeline import (
    document_status_counts,
    refresh_documents_by_status_gauge,
    track_document_failed,
    track_document_processed,
    track_watcher_error,
    track_worker_init_failure,
    update_queue_status_snapshot,
)
from .rag import (
    track_chunk_weight_adjustment,
    track_feedback_vote,
    track_mmr,
    track_prompt_injection_attempts,
    track_query_transform,
)
from .endpoint import (
    get_metrics,
    register_metrics_endpoint,
    render_metrics,
)
from .labels import escape_label, metric_key

# Backward-compatible aliases for the legacy underscore-prefixed
# names the original ``services/metrics.py`` exposed.
_track_ocr_cascade_fallback = track_ocr_cascade_fallback
_track_ocr_dpi_escalation = track_ocr_dpi_escalation
_track_ocr_duration = track_ocr_duration
_track_ocr_language_detected = track_ocr_language_detected
_track_ocr_language_threshold_used = track_ocr_language_threshold_used
_track_ocr_postprocess = track_ocr_postprocess
_track_ocr_skip_tier2 = track_ocr_skip_tier2
_track_ocr_tier_used = track_ocr_tier_used
_track_embedding_latency = track_embedding_latency
_track_embedding_fallback = track_embedding_fallback
_track_search_latency = track_search_latency
_track_search_strategy_used = track_search_strategy_used
_track_cache_hit = track_cache_hit
_track_cache_miss = track_cache_miss
_track_document_processed = track_document_processed
_track_document_failed = track_document_failed
_track_watcher_error = track_watcher_error
_track_query_transform = track_query_transform
_track_mmr = track_mmr
_track_prompt_injection_attempts = track_prompt_injection_attempts
_track_feedback_vote = track_feedback_vote
_track_chunk_weight_adjustment = track_chunk_weight_adjustment
_get_prometheus_text = render_metrics
get_prometheus_text = render_metrics
_update_queue_status_snapshot = update_queue_status_snapshot
_register_metrics_endpoint = register_metrics_endpoint
_label = escape_label
_metric_key = metric_key

__all__ = [
    # OCR
    "track_ocr_duration",
    "track_ocr_cascade_fallback",
    "track_ocr_dpi_escalation",
    "track_ocr_postprocess",
    "track_ocr_tier_used",
    "track_ocr_skip_tier2",
    "track_ocr_language_detected",
    "track_ocr_language_threshold_used",
    # Embedding
    "track_embedding_latency",
    "track_embedding_duration",
    "track_embedding_fallback",
    # Search
    "track_search_latency",
    "track_search_strategy_used",
    "track_cache_hit",
    "track_cache_miss",
    "update_cache_hit_rate",
    # Pipeline
    "track_document_processed",
    "track_document_failed",
    "track_watcher_error",
    "update_queue_status_snapshot",
    "document_status_counts",
    "refresh_documents_by_status_gauge",
    # RAG
    "track_query_transform",
    "track_mmr",
    "track_prompt_injection_attempts",
    "track_feedback_vote",
    "track_chunk_weight_adjustment",
    # Endpoint
    "render_metrics",
    "get_metrics",
    "register_metrics_endpoint",
    # Labels
    "escape_label",
    "metric_key",
    # Legacy aliases
    "_track_ocr_duration",
    "_track_ocr_cascade_fallback",
    "_track_ocr_dpi_escalation",
    "_track_ocr_postprocess",
    "_track_ocr_tier_used",
    "_track_ocr_skip_tier2",
    "_track_ocr_language_detected",
    "_track_ocr_language_threshold_used",
    "_track_embedding_latency",
    "_track_embedding_fallback",
    "_track_search_latency",
    "_track_search_strategy_used",
    "_track_cache_hit",
    "_track_cache_miss",
    "_track_document_processed",
    "_track_document_failed",
    "_track_watcher_error",
    "_track_query_transform",
    "_track_mmr",
    "_track_prompt_injection_attempts",
    "_track_feedback_vote",
    "_track_chunk_weight_adjustment",
    "_get_prometheus_text",
    "get_prometheus_text",
    "_update_queue_status_snapshot",
    "_register_metrics_endpoint",
    "_label",
    "_metric_key",
]
