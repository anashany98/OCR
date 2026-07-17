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

# OvisOCR2 is a separate GPU service.  Its document/page identifiers belong
# in structured logs, never in Prometheus labels; these bounded labels keep
# its operational signals safe to scrape at production scale.
OVISOCR2_REQUESTS = Counter(
    "docuintel_ovisocr2_requests_total",
    "OvisOCR2 requests by bounded outcome and eligibility reason.",
    labelnames=("outcome", "reason"),
)
OVISOCR2_DURATION = Histogram(
    "docuintel_ovisocr2_duration_seconds",
    "OvisOCR2 end-to-end request duration in seconds.",
    labelnames=("outcome",),
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 180.0),
)
OVISOCR2_OUTPUT_FEATURES = Counter(
    "docuintel_ovisocr2_output_features_total",
    "OvisOCR2 parsed output features and warnings.",
    labelnames=("feature",),
)

# Docling PDF parser. Same bounded label vocabulary as OvisOCR2 so the
# two external services share a metric style and stay easy to compare.
DOCLING_REQUESTS = Counter(
    "docuintel_docling_requests_total",
    "Docling PDF parser requests by bounded outcome.",
    labelnames=("outcome", "reason"),
)
DOCLING_DURATION = Histogram(
    "docuintel_docling_duration_seconds",
    "Docling end-to-end request duration in seconds.",
    labelnames=("outcome",),
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)
DOCLING_PAGES = Counter(
    "docuintel_docling_pages_total",
    "Docling page split between digital text and scanned image, per request.",
    labelnames=("kind",),
)
# Tracks when the parser router had to fall back from the Docling
# service to the legacy ``parse_pdf`` so an operator can see the
# degradation in /metrics. Each ``reason`` value is one of the
# bounded enum constants the helper accepts.
DOCLING_FALLBACK = Counter(
    "docuintel_docling_fallback_total",
    "Docling-to-legacy fallback events, by reason.",
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
STALE_JOBS_RESET = Counter(
    "docuintel_stale_jobs_reset_total",
    "Stale processing jobs reset by the sweeper.",
)
NOTIFICATION_FAILURES = Counter(
    "docuintel_notification_failures_total",
    "Failed notification deliveries.",
    labelnames=("channel",),
)
EMBEDDING_COVERAGE = Gauge(
    "docuintel_embedding_coverage_ratio",
    "Fraction of document chunks with embeddings.",
)

# ---------------------------------------------------------------------------
# CR1 — AI source persistence metrics
# ---------------------------------------------------------------------------

AI_SOURCE_STALE_BLOCK = Counter(
    "docuintel_ai_source_stale_block_total",
    "AI answer sources saved with block_id=NULL because the block no longer exists.",
)

AI_STREAM_PERSIST_FAILURE = Counter(
    "docuintel_ai_stream_persist_failure_total",
    "AI stream answer persistence failures.",
    labelnames=("stage",),
)

# ---------------------------------------------------------------------------
# CR4 — Exact document search metrics
# ---------------------------------------------------------------------------

EXACT_SEARCH = Counter(
    "docuintel_exact_document_search_total",
    "Exact document search outcomes.",
    labelnames=("kind", "outcome"),
)

EXACT_SEARCH_LATENCY = Histogram(
    "docuintel_exact_document_search_latency_seconds",
    "Exact document search wall-clock duration.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# ---------------------------------------------------------------------------
# CR3 — Follow-up resolution metrics
# ---------------------------------------------------------------------------

FOLLOWUP_RESOLUTION = Counter(
    "docuintel_ai_followup_resolution_total",
    "Follow-up question resolution outcomes.",
    labelnames=("kind", "outcome"),
)

# ---------------------------------------------------------------------------
# CR8 — Answers without sources
# ---------------------------------------------------------------------------

ANSWERS_WITHOUT_SOURCES = Counter(
    "docuintel_ai_answers_without_sources_total",
    "AI answers persisted without any cited source.",
    labelnames=("reason",),
)

# ---------------------------------------------------------------------------
# CR11 — Review pipeline metrics
# ---------------------------------------------------------------------------

REVIEW_DOCUMENTS = Counter(
    "docuintel_review_documents_total",
    "Documents classified for review.",
    labelnames=("reason", "severity"),
)

REVIEW_AUTO_RESOLVED = Counter(
    "docuintel_review_auto_resolved_total",
    "Review decisions auto-resolved by the quality pipeline.",
    labelnames=("reason",),
)

# ---------------------------------------------------------------------------
# CR9 — OCR render permission failures
# ---------------------------------------------------------------------------

OCR_RENDER_PERMISSION_FAILURES = Counter(
    "docuintel_ocr_render_permission_failure_total",
    "Permission denied errors when rendering pages for OCR.",
)

OCR_TIER_AVAILABLE = Gauge(
    "docuintel_ocr_tier_available",
    "Whether a given OCR tier is available at runtime.",
    labelnames=("tier",),
)

# ---------------------------------------------------------------------------
# P0.1 — Per-stage pipeline timing histograms
# ---------------------------------------------------------------------------

STAGE_DURATION = Histogram(
    "docuintel_stage_duration_seconds",
    "Per-stage processing wall-clock duration in seconds.",
    labelnames=("stage",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

STAGE_FAILURES = Counter(
    "docuintel_stage_failures_total",
    "Stage-level processing failures.",
    labelnames=("stage", "reason"),
)

PAGES_PROCESSED = Counter(
    "docuintel_pages_processed_total",
    "Pages processed, broken down by routing and engine.",
    labelnames=("route", "engine"),
)

# ---------------------------------------------------------------------------
# MiniMax M3 — chat path instrumentation
# ---------------------------------------------------------------------------
# Stages measured inside the /api/v1/ai/ask and /api/v1/ai/ask/stream
# handlers. The label set is bounded by the ``stage`` enum passed by
# the caller; the same value is reused across counters and histograms
# so an operator can join "duration" and "outcome" by stage.
#
# Stages currently emitted:
#   reference_resolution, tool_selection, scope_enforcement,
#   context_collection, confidence_gates, memory_block,
#   grounded_response, source_sanitization, persistence,
#   cache_lookup, cache_write
# ---------------------------------------------------------------------------

CHAT_STAGE_DURATION = Histogram(
    "docuintel_chat_stage_duration_seconds",
    "Wall-clock duration of each chat path stage in seconds.",
    labelnames=("stage",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

CHAT_STAGE_OUTCOME = Counter(
    "docuintel_chat_stage_outcome_total",
    "Chat path stage outcomes, broken down by stage and outcome.",
    labelnames=("stage", "outcome"),
)

# Bounded variants for the search/retrieval sub-paths. ``strategy``
# matches the existing search_service vocabulary (exact, structured,
# hybrid, semantic, multi_query). ``outcome`` is one of hit, miss,
# skipped, error.
CHAT_RETRIEVAL_DURATION = Histogram(
    "docuintel_chat_retrieval_duration_seconds",
    "Retrieval sub-path wall-clock duration in seconds.",
    labelnames=("strategy",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

CHAT_RETRIEVAL_OUTCOME = Counter(
    "docuintel_chat_retrieval_outcome_total",
    "Retrieval sub-path outcomes, broken down by strategy.",
    labelnames=("strategy", "outcome"),
)

# Cache lookup is split into exact vs semantic so operators can see
# which is contributing to the hit rate. ``outcome`` is one of hit,
# miss, error, disabled.
CHAT_CACHE_LOOKUP = Counter(
    "docuintel_chat_cache_lookup_total",
    "AI cache lookups inside the chat path.",
    labelnames=("kind", "outcome"),
)

CHAT_CACHE_LOOKUP_LATENCY = Histogram(
    "docuintel_chat_cache_lookup_seconds",
    "AI cache lookup wall-clock duration in seconds.",
    labelnames=("kind",),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

# Streaming milestones. ``event`` is one of start, delta, end, error.
# No user content is ever put in labels.
CHAT_STREAM_FIRST_EVENT = Histogram(
    "docuintel_chat_stream_first_event_seconds",
    "Time from request to first SSE event, broken down by event type.",
    labelnames=("event",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

CHAT_STREAM_TOTAL = Histogram(
    "docuintel_chat_stream_total_seconds",
    "Total wall-clock duration of a /ask/stream call, from request to last event.",
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# ---------------------------------------------------------------------------
# MiniMax M3 — extraction fingerprint
# ---------------------------------------------------------------------------
# FASE 3 records one row per HyperExtract attempt, labeled by the
# outcome (``success``, ``invalid_json``, ``repaired``, ``timeout``,
# ``provider_error``, ``skipped``, ``cache_hit``), the route
# (``deterministic``, ``llm_text``, ``vlm``) and the size class
# (``small``, ``medium``, ``large``). The fingerprint hash itself is
# never emitted as a label.
# ---------------------------------------------------------------------------

EXTRACTION_FINGERPRINT_RESULT = Counter(
    "docuintel_extraction_fingerprint_result_total",
    "Structured extraction outcomes, broken down by fingerprint outcome and route.",
    labelnames=("route", "outcome", "size_class"),
)

EXTRACTION_FINGERPRINT_DURATION = Histogram(
    "docuintel_extraction_fingerprint_duration_seconds",
    "Structured extraction wall-clock duration in seconds, broken down by route and outcome.",
    labelnames=("route", "outcome"),
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)

EXTRACTION_FINGERPRINT_REUSED = Counter(
    "docuintel_extraction_fingerprint_reused_total",
    "Structured extraction attempts that were skipped because the fingerprint matched a prior valid result.",
    labelnames=("route",),
)

# ---------------------------------------------------------------------------
# MiniMax M3 — classification instrumentation
# ---------------------------------------------------------------------------
# FASE 2 records the layer that produced the final document_type
# (source_format, filename, parser, learned, llm). ``dimension`` is
# the classification axis being measured (``source_format`` vs
# ``document_type``); ``path`` is the layer that won.
# ---------------------------------------------------------------------------

CLASSIFICATION_LAYER = Counter(
    "docuintel_classification_layer_total",
    "Documents classified, broken down by winning layer and dimension.",
    labelnames=("dimension", "path", "size_class"),
)

CLASSIFICATION_RECLASSIFY = Counter(
    "docuintel_classification_reclassify_total",
    "Reclassification attempts, broken down by whether OCR/extraction was relaunched.",
    labelnames=("relauched_ocr", "relauched_extraction"),
)
