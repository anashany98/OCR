"""Prometheus metric definitions, shared across the metrics package.

The original ``services/metrics.py`` carried the Prometheus
exposition format as a hand-written ``"\\n".join(lines)`` block.
That worked but it had three drawbacks:

1. **Easy to forget a label** when adding a new counter (the
   code had to know the OpenMetrics quoting rules).
2. **No histograms.** Latencies were tracked as ``_sum`` and
   ``_count`` plain floats, so the operator could not ask
   Grafana for ``p95 embedding latency``.
3. **Hand-crafted text format** is one of the things the
   official ``prometheus_client`` library exists to avoid.

This module centralises the metric *definitions* (Counter,
Histogram, Gauge). Sub-modules (``ocr``, ``embedding``, ``search``,
``pipeline``, ``rag``) own the ``track_*`` functions that
update them. The renderer (``endpoint``) uses
``prometheus_client.generate_latest`` to format the response.

We use the default global ``REGISTRY`` so the rest of the
codebase (including the FastAPI route) does not need to know
about CollectorRegistry plumbing. Tests can still reset the
counters with ``prometheus_client.REGISTRY.unregister`` if they
need a clean slate.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# OCR metrics
# ---------------------------------------------------------------------------
# We use Histogram for the per-request duration so the operator
# can ask for ``rate(docuintel_ocr_duration_seconds_sum[5m]) /
# rate(docuintel_ocr_duration_seconds_count[5m])`` to get the
# average latency, or pull p95/p99 from the histogram buckets.

OCR_DURATION = Histogram(
    "docuintel_ocr_duration_seconds",
    "OCR processing wall-clock duration in seconds.",
    labelnames=("tier", "language"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# Tier used (S0.2) and per-tier by document type. ``tier`` and
# ``document_type`` are the only labels. The bounded card sets
# are documented in the original metrics.py module.
OCR_TIER_USED = Counter(
    "docuintel_ocr_tier_used_total",
    "OCR winning-tier counts.",
    labelnames=("tier",),
)
OCR_TIER_BY_DOC_TYPE = Counter(
    "docuintel_ocr_tier_by_doc_type",
    "OCR winning-tier counts broken down by document type.",
    labelnames=("tier", "document_type"),
)

# DPI ladder (O1). The label set is bounded: 2 transitions
# (300->400, 400->600).
OCR_DPI_ESCALATION = Counter(
    "docuintel_ocr_dpi_escalation_total",
    "DPI ladder escalations (small text re-rendered at higher DPI).",
    labelnames=("from_dpi", "to_dpi"),
)

# Post-process corrections (O4).
OCR_POSTPROCESS_CORRECTIONS = Counter(
    "docuintel_ocr_postprocess_corrections_total",
    "OCR post-process corrections applied.",
)

# Skip tier 2 (S0.6).
OCR_SKIP_TIER2 = Counter(
    "docuintel_ocr_skip_tier2_total",
    "Cascade decisions to keep the primary result instead of replacing with Tier 2.",
    labelnames=("reason",),
)

# M1 (Sprint 3): Tier 4 (VLM) invocation reason. The cascade only
# consults ``vlm_ocr`` when the best Tier 1-3 result is still below
# ``tier4_quality_threshold``; this counter records *why* it fired
# (under-threshold vs. explicit call) so the operator can see in
# Grafana whether Tier 4 is being invoked because the rest of the
# cascade is weak (the bad case) or because the page is genuinely
# outside the OCR engines' coverage (the expected case). The
# bounded label set is the ``reason`` enum passed by the caller.
OCR_TIER4_INVOKED = Counter(
    "docuintel_ocr_tier4_invoked_total",
    "Tier 4 (VLM) invocations, by reason.",
    labelnames=("reason",),
)

# Cascade fallback (O4 — error visibility).
OCR_CASCADE_FALLBACK = Counter(
    "docuintel_ocr_cascade_fallback_total",
    "OCR cascade fallback failures.",
    labelnames=("engine", "reason"),
)

# Per-page language detection (O2). Bounded: (language,
# document_type).
OCR_LANGUAGE_DETECTED = Counter(
    "docuintel_ocr_language_detected_total",
    "Per-page language detections.",
    labelnames=("language", "document_type"),
)
OCR_LANGUAGE_THRESHOLD_USED = Counter(
    "docuintel_ocr_language_threshold_used",
    "Per-language threshold consultations.",
    labelnames=("language", "threshold_type"),
)

# ---------------------------------------------------------------------------
# Embedding metrics
# ---------------------------------------------------------------------------

EMBEDDING_DURATION = Histogram(
    "docuintel_embedding_duration_seconds",
    "Embedding call wall-clock duration in seconds.",
    labelnames=("model",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
EMBEDDING_FALLBACKS = Counter(
    "docuintel_embedding_fallbacks_total",
    "Embedding fallback generations (hash used because the real model was down).",
)

# ---------------------------------------------------------------------------
# Search metrics
# ---------------------------------------------------------------------------

SEARCH_DURATION = Histogram(
    "docuintel_search_duration_seconds",
    "Search wall-clock duration in seconds.",
    labelnames=("strategy",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
SEARCH_STRATEGY_USED = Counter(
    "docuintel_search_strategy_used",
    "Per-strategy retrieval outcomes.",
    labelnames=("strategy", "outcome"),
)
CACHE_HITS = Counter(
    "docuintel_cache_hits_total",
    "Cache hits.",
)
CACHE_MISSES = Counter(
    "docuintel_cache_misses_total",
    "Cache misses.",
)
CACHE_HIT_RATE = Gauge(
    "docuintel_cache_hit_rate",
    "Cache hit rate (0-1). Computed from CACHE_HITS / (CACHE_HITS + CACHE_MISSES).",
)

# ---------------------------------------------------------------------------
# Pipeline metrics (ingestion, watcher)
# ---------------------------------------------------------------------------

DOCUMENTS_PROCESSED = Counter(
    "docuintel_documents_processed_total",
    "Documents processed.",
)
DOCUMENTS_FAILED = Counter(
    "docuintel_documents_failed_total",
    "Documents failed.",
)
DOCUMENTS_BY_STATUS = Gauge(
    "docuintel_documents_by_status",
    "Documents grouped by status. Updated from the DB on /metrics scrape.",
    labelnames=("status",),
)
JOBS_PENDING_BY_QUEUE = Gauge(
    "docuintel_jobs_pending_by_queue",
    "Pending jobs by Celery queue. Updated from the worker snapshot on /metrics scrape.",
    labelnames=("queue",),
)
WATCHER_ERRORS = Counter(
    "docuintel_watcher_errors_total",
    "Watcher ingestion errors.",
)

# OCR-INIT-1 (Sprint 2): tracks failures of the Celery
# ``worker_process_init`` hook (model preload, GPU init, etc.).
# The bounded label set is the ``stage`` name passed by the
# caller (``ocr_preload``, ``yolo_preload``, …); values outside
# the allow-list are bucketed to ``"other"`` by the ``track_*``
# helper to keep the cardinality controlled.
WORKER_INIT_FAILURES = Counter(
    "docuintel_worker_init_failures_total",
    "Worker process init failures (e.g. OCR engine preload).",
    labelnames=("stage",),
)

# OPS-2: failure counters for the parser fallbacks that used to
# swallow exceptions silently. Each one has a bounded ``kind``
# label (table_strategy, vision_image, vision_table, pdfplumber_import)
# so the operator can see WHICH fallback degraded and how often,
# not just that "some doc came out without entities".
PARSER_FALLBACK_FAILURES = Counter(
    "docuintel_parser_fallback_failures_total",
    "Failures swallowed by parser fallbacks (vision transcription, table extraction, …).",
    labelnames=("stage", "kind"),
)

# ---------------------------------------------------------------------------
# RAG / chat metrics (R1, R2, R3, E5)
# ---------------------------------------------------------------------------

QUERY_TRANSFORM = Counter(
    "docuintel_query_transform_total",
    "Query transformer outcomes.",
    labelnames=("method", "outcome"),
)
QUERY_TRANSFORM_LATENCY = Histogram(
    "docuintel_query_transform_latency_ms",
    "Query-transformer call latency in milliseconds.",
    labelnames=("method",),
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10_000),
)
MMR_OUTCOMES = Counter(
    "docuintel_mmr_total",
    "MMR reranker outcomes.",
    labelnames=("outcome",),
)
MMR_AVG_PAIRWISE_SIMILARITY = Gauge(
    "docuintel_mmr_avg_pairwise_similarity",
    "Average pairwise similarity of MMR picks (lower = more diverse).",
    labelnames=("outcome",),
)
PROMPT_INJECTION_ATTEMPTS = Counter(
    "docuintel_prompt_injection_attempts",
    "Detected prompt-injection attempts in the RAG context.",
    labelnames=("action", "sensitivity", "score_bucket"),
)
FEEDBACK_VOTES = Counter(
    "docuintel_feedback_votes",
    "Recorded feedback votes on AI answers.",
    labelnames=("vote", "reason"),
)
CHUNK_WEIGHT_ADJUSTMENTS = Counter(
    "docuintel_chunk_weight_adjustments",
    "Chunk weight adjustments triggered by feedback.",
    labelnames=("direction", "source_count_bucket"),
)
