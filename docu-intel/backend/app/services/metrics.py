from __future__ import annotations

import time
from functools import wraps
from typing import Callable

from fastapi import FastAPI, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.models import Document

# In-memory metrics (for simple deployment)
# For production, use prometheus_client with Pushgateway or exposed endpoint
_metrics: dict[str, float] = {
    "ocr_duration_sum": 0.0,
    "ocr_duration_count": 0,
    "embedding_latency_sum": 0.0,
    "embedding_latency_count": 0,
    "search_latency_sum": 0.0,
    "search_latency_count": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "documents_processed": 0,
    "documents_failed": 0,
    "embedding_fallback_count": 0,
    "watcher_errors": 0,
    "documents_processed": 0,
    "documents_failed": 0,
    "embedding_fallbacks": 0,
    "watcher_errors": 0,
}

_queue_pending_by_name: dict[str, int] = {}
_ocr_cascade_fallbacks: dict[tuple[str, str], int] = {}
_ocr_tier_used: dict[str, int] = {}
# S0.2 — per-tier breakdown by document type. ``(tier, doc_type)``
# is the Prometheus label set. Bounded cardinality: 4 tiers
# (tesseract, paddleocr, pp_structure, dots_mocr) times ~7
# document_types = 28 series max.
_ocr_tier_by_doc_type: dict[tuple[str, str], int] = {}
# O1 — DPI escalation counter. ``(from_dpi, to_dpi)`` is the
# Prometheus label set. Bounded: only 2 transitions possible
# (300→400, 400→600).
_ocr_dpi_escalations: dict[tuple[str, str], int] = {}
# O4 — OCR post-process corrections. ``correction_count`` is
# the number of corrections applied to a single page.
_ocr_postprocess_corrections: int = 0
# S0.6 — reason the cascade decided to keep the primary result instead
# of replacing it with the Tier 2 fallback. Keys are short labels so
# the Prometheus label cardinality stays bounded.
_ocr_skip_tier2: dict[str, int] = {}
# O2 — per-page language detection counters. The label set is
# bounded: (language, document_type). Unknown languages bucket
# under "unknown" so the cardinality cannot explode.
_ocr_language_detected: dict[tuple[str, str], int] = {}
_ocr_language_threshold_used: dict[tuple[str, str], int] = {}
# E2 — per-strategy retrieval counters. ``strategy`` is one of
# ``bm25``, ``cosine``, ``text``; ``outcome`` is ``executed``,
# ``failed``, ``skipped_non_postgres``.
_search_strategy_used: dict[tuple[str, str], int] = {}
# R1 — query transformer outcomes. ``method`` is
# ``"hyde" | "multi_query" | "auto" | "off"``; ``outcome`` is
# ``"success" | "fallback" | "disabled"``. The latency is
# recorded as a separate histogram (kept small to avoid blowing
# up the in-memory metrics state).
_query_transform: dict[tuple[str, str], int] = {}
_query_transform_latency_sum: dict[str, int] = {}
_query_transform_latency_count: dict[str, int] = {}
# E5 — MMR reranker outcomes. ``outcome`` is ``"diversified"``
# (MMR re-ordered the input), ``"passthrough"`` (input too
# small, returned top-k by relevance unchanged), ``"empty"``
# (no input).
_mmr_outcomes: dict[str, int] = {}
# Histogram of avg_pairwise_similarity per outcome. Stored as a
# simple running mean so we can show it in the admin UI
# without pulling in a real histogram library.
_mmr_avg_sim_sum: dict[str, float] = {}
_mmr_avg_sim_count: dict[str, int] = {}
# R2 — prompt-injection attempts. ``action`` is
# ``"logged"``, ``"sanitised"``, ``"dropped"``; ``sensitivity``
# is the operator-chosen threshold; ``score_bucket`` keeps
# the label set small.
_prompt_injection_attempts: dict[tuple[str, str, str], int] = {}
# R3 — feedback loop. ``vote`` is ``"+1"`` or ``"-1"`` (the
# signed int as a label string); ``reason`` is the optional
# reason the user picked.
_feedback_votes: dict[tuple[str, str], int] = {}
_chunk_weight_adjustments: dict[tuple[str, str], int] = {}


def track_ocr_duration(duration: float) -> None:
    _metrics["ocr_duration_sum"] += duration
    _metrics["ocr_duration_count"] += 1


def track_ocr_cascade_fallback(engine_name: str, reason: str) -> None:
    key = (engine_name or "unknown", reason or "unknown")
    _ocr_cascade_fallbacks[key] = _ocr_cascade_fallbacks.get(key, 0) + 1


def track_ocr_dpi_escalation(*, from_dpi: int, to_dpi: int) -> None:
    """Record that the OCR DPI ladder escalated from one DPI to
    another because Tier 1 produced a weak result. ``from_dpi``
    and ``to_dpi`` are the DPI values before and after the
    re-render (e.g. 300 and 400).
    """
    key = (str(from_dpi), str(to_dpi))
    _ocr_dpi_escalations[key] = _ocr_dpi_escalations.get(key, 0) + 1


def track_ocr_postprocess(*, correction_count: int) -> None:
    """Record the number of corrections applied by the OCR
    post-processor to a single page. The running total is
    exposed as a Prometheus counter so the admin UI can show
    how many corrections the system is making in production.
    """
    global _ocr_postprocess_corrections
    _ocr_postprocess_corrections += max(0, correction_count)


def track_ocr_tier_used(tier: str, document_type: str | None = None) -> None:
    clean_tier = tier or "unknown"
    _ocr_tier_used[clean_tier] = _ocr_tier_used.get(clean_tier, 0) + 1
    if document_type:
        clean_doc = (document_type or "unknown").lower().strip() or "unknown"
        key = (clean_tier, clean_doc)
        _ocr_tier_by_doc_type[key] = _ocr_tier_by_doc_type.get(key, 0) + 1


def track_ocr_skip_tier2(reason: str) -> None:
    """Record that the cascade kept the primary result instead of
    replacing it with the Tier 2 fallback. ``reason`` is a short label
    such as ``"no_significant_gain"``, ``"both_weak"`` or
    ``"alnum_below_threshold"`` so the admin UI can break down *why*
    Tier 2 was skipped on any given page.
    """
    clean_reason = reason or "unknown"
    _ocr_skip_tier2[clean_reason] = _ocr_skip_tier2.get(clean_reason, 0) + 1


def track_ocr_language_detected(language: str, document_type: str) -> None:
    """Record the language the parser detected for a page.

    ``language`` is the ISO-639-1 code (or ``"unknown"``). ``document_type``
    is the parsed document's type (e.g. ``"presupuesto"``). The label set
    is bounded: languages not in our short whitelist bucket under
    ``"unknown"`` so Prometheus label cardinality stays in check.
    """
    clean_lang = (language or "unknown").lower().strip() or "unknown"
    clean_doc = (document_type or "unknown").lower().strip() or "unknown"
    key = (clean_lang, clean_doc)
    _ocr_language_detected[key] = _ocr_language_detected.get(key, 0) + 1


def track_ocr_language_threshold_used(language: str, threshold_type: str) -> None:
    """Record which per-language threshold the cascade consulted.

    ``threshold_type`` is one of ``"min_chars"`` or ``"min_confidence"``.
    Together with ``track_ocr_language_detected`` this gives the admin
    UI a per-language breakdown of which thresholds are actually in
    play in production.
    """
    clean_lang = (language or "unknown").lower().strip() or "unknown"
    clean_t = (threshold_type or "unknown").lower().strip() or "unknown"
    key = (clean_lang, clean_t)
    _ocr_language_threshold_used[key] = _ocr_language_threshold_used.get(key, 0) + 1


def track_search_strategy_used(strategy: str, outcome: str) -> None:
    """Record which retrieval strategy was used (and how) for a search.

    ``strategy`` is one of ``"bm25"``, ``"cosine"``, ``"text"``,
    ``"hybrid"``. ``outcome`` is ``"executed"``, ``"failed"``,
    ``"skipped_non_postgres"`` (for the BM25 branch on SQLite).
    """
    clean_strategy = (strategy or "unknown").lower().strip() or "unknown"
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    key = (clean_strategy, clean_outcome)
    _search_strategy_used[key] = _search_strategy_used.get(key, 0) + 1


def track_query_transform(method: str, outcome: str, *, latency_ms: int = 0) -> None:
    """Record a query-transformer call.

    ``method`` is the strategy requested (``"hyde"``,
    ``"multi_query"``, ``"auto"`` after resolution, or ``"off"``).
    ``outcome`` is ``"success"`` (LLM produced a parseable
    response), ``"fallback"`` (LLM was unavailable / unparseable,
    the original query was returned), or ``"disabled"`` (the
    transformer was off for this call). ``latency_ms`` is the
    wall-clock time spent in the LLM call; the value is added
    to a per-method latency histogram so the admin UI can show
    ``avg query-transform latency``.
    """
    clean_method = (method or "unknown").lower().strip() or "unknown"
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    _query_transform[(clean_method, clean_outcome)] = _query_transform.get(
        (clean_method, clean_outcome), 0
    ) + 1
    if latency_ms and latency_ms > 0:
        _query_transform_latency_sum[clean_method] = (
            _query_transform_latency_sum.get(clean_method, 0) + int(latency_ms)
        )
        _query_transform_latency_count[clean_method] = (
            _query_transform_latency_count.get(clean_method, 0) + 1
        )


def track_mmr(outcome: str, *, avg_similarity: float = 0.0) -> None:
    """Record a Maximal Marginal Relevance rerank call.

    ``outcome`` is one of ``"diversified"`` (MMR re-ordered the
    input), ``"passthrough"`` (input was too small or
    ``lambda=1``, returned top-k by relevance unchanged),
    ``"passthrough_lambda_one"`` (specifically the lambda=1
    short-circuit), or ``"empty"`` (no input). ``avg_similarity``
    is the average n-gram Jaccard similarity between the chosen
    hits; the running mean is reported as a Prometheus gauge
    so the admin UI can see how diverse the picks really are.
    """
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    _mmr_outcomes[clean_outcome] = _mmr_outcomes.get(clean_outcome, 0) + 1
    if avg_similarity and avg_similarity >= 0.0:
        _mmr_avg_sim_sum[clean_outcome] = (
            _mmr_avg_sim_sum.get(clean_outcome, 0.0) + float(avg_similarity)
        )
        _mmr_avg_sim_count[clean_outcome] = (
            _mmr_avg_sim_count.get(clean_outcome, 0) + 1
        )


def track_prompt_injection_attempts(
    *, action: str, sensitivity: str, score_bucket: str
) -> None:
    """Record a prompt-injection attempt detected by
    :mod:`app.services.prompt_sanitizer`.

    ``action`` is the action taken by the caller (``"logged"``,
    ``"sanitised"``, ``"dropped"``). ``sensitivity`` is the
    operator-chosen threshold. ``score_bucket`` keeps the
    label set small (one of ``"low" | "medium" | "high" | "very_high"``).
    """
    clean_action = (action or "unknown").lower().strip() or "unknown"
    clean_sens = (sensitivity or "unknown").lower().strip() or "unknown"
    clean_bucket = (score_bucket or "unknown").lower().strip() or "unknown"
    key = (clean_action, clean_sens, clean_bucket)
    _prompt_injection_attempts[key] = _prompt_injection_attempts.get(key, 0) + 1


def track_feedback_vote(*, vote: str, reason: str) -> None:
    """Record a 👍/👎 vote on an AI answer.

    ``vote`` is the string form of ``+1`` or ``-1``; ``reason``
    is one of the allowed reasons or ``"none"`` / ``"duplicate"``
    / ``"invalid_vote"`` / ``"answer_not_found"`` for the
    bookkeeping outcomes.
    """
    clean_vote = (vote or "unknown").strip() or "unknown"
    clean_reason = (reason or "none").strip().lower() or "none"
    key = (clean_vote, clean_reason)
    _feedback_votes[key] = _feedback_votes.get(key, 0) + 1


def track_chunk_weight_adjustment(*, direction: str, source_count: int) -> None:
    """Record a chunk-weight adjustment.

    ``direction`` is one of ``"up"``, ``"down"``, ``"neutral"``,
    ``"rebalanced"``. ``source_count`` is how many source rows
    the loop touched. We bucket ``source_count`` into ``"1"``,
    ``"2_5"``, ``"6_20"``, ``"21_plus"`` to keep the label
    cardinality bounded.
    """
    clean_direction = (direction or "unknown").lower().strip() or "unknown"
    if source_count <= 1:
        bucket = "1"
    elif source_count <= 5:
        bucket = "2_5"
    elif source_count <= 20:
        bucket = "6_20"
    else:
        bucket = "21_plus"
    key = (clean_direction, bucket)
    _chunk_weight_adjustments[key] = _chunk_weight_adjustments.get(key, 0) + 1


def track_embedding_latency(duration: float) -> None:
    _metrics["embedding_latency_sum"] += duration
    _metrics["embedding_latency_count"] += 1


def track_search_latency(duration: float) -> None:
    _metrics["search_latency_sum"] += duration
    _metrics["search_latency_count"] += 1


def track_cache_hit() -> None:
    _metrics["cache_hits"] += 1


def track_cache_miss() -> None:
    _metrics["cache_misses"] += 1


def track_document_processed(count: int = 1) -> None:
    _metrics["documents_processed"] += count


def track_document_failed(count: int = 1) -> None:
    _metrics["documents_failed"] += count


def track_embedding_fallback(count: int = 1) -> None:
    _metrics["embedding_fallbacks"] += count


def track_watcher_error(count: int = 1) -> None:
    _metrics["watcher_errors"] += count


def update_queue_status_snapshot(snapshot) -> None:
    queues = getattr(snapshot, "queues", snapshot) or {}
    _queue_pending_by_name.clear()
    for queue_name, values in queues.items():
        if isinstance(values, dict):
            _queue_pending_by_name[str(queue_name)] = int(values.get("pending", 0) or 0)


def document_status_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(Document.status, func.count()).where(Document.deleted_at.is_(None)).group_by(Document.status)).all()
    return {str(status): int(count) for status, count in rows}


def track_document_processed() -> None:
    _metrics["documents_processed"] += 1


def track_document_failed() -> None:
    _metrics["documents_failed"] += 1


def track_embedding_fallback() -> None:
    _metrics["embedding_fallback_count"] += 1


def track_watcher_error() -> None:
    _metrics["watcher_errors"] += 1


def get_metrics() -> dict[str, float]:
    data = _metrics.copy()
    for queue_name, pending in _queue_pending_by_name.items():
        data[f"jobs_pending_{queue_name}"] = float(pending)
    data["ocr_cascade_fallback_total"] = float(sum(_ocr_cascade_fallbacks.values()))
    for (engine_name, reason), count in _ocr_cascade_fallbacks.items():
        suffix = f"{_metric_key(engine_name)}_{_metric_key(reason)}"
        data[f"ocr_cascade_fallback_total_{suffix}"] = float(count)
    for tier, count in _ocr_tier_used.items():
        data[f"ocr_tier_used_total_{_metric_key(tier)}"] = float(count)
    for (tier, doc_type), count in _ocr_tier_by_doc_type.items():
        data[f"ocr_tier_by_doc_type_{_metric_key(tier)}_{_metric_key(doc_type)}"] = float(count)
    data["ocr_dpi_escalation_total"] = float(sum(_ocr_dpi_escalations.values()))
    for (from_dpi, to_dpi), count in _ocr_dpi_escalations.items():
        data[f"ocr_dpi_escalation_total_{from_dpi}_to_{to_dpi}"] = float(count)
    data["ocr_postprocess_corrections_total"] = float(_ocr_postprocess_corrections)
    data["ocr_skip_tier2_total"] = float(sum(_ocr_skip_tier2.values()))
    for reason, count in _ocr_skip_tier2.items():
        data[f"ocr_skip_tier2_total_{_metric_key(reason)}"] = float(count)
    data["ocr_language_detected_total"] = float(sum(_ocr_language_detected.values()))
    for (lang, doc_type), count in _ocr_language_detected.items():
        data[f"ocr_language_detected_total_{_metric_key(lang)}_{_metric_key(doc_type)}"] = float(count)
    for (lang, threshold_type), count in _ocr_language_threshold_used.items():
        data[f"ocr_language_threshold_used_{_metric_key(lang)}_{_metric_key(threshold_type)}"] = float(count)
    for (strategy, outcome), count in _search_strategy_used.items():
        data[f"search_strategy_used_{_metric_key(strategy)}_{_metric_key(outcome)}"] = float(count)
    for (method, outcome), count in _query_transform.items():
        data[f"query_transform_{_metric_key(method)}_{_metric_key(outcome)}"] = float(count)
    for method, total in _query_transform_latency_sum.items():
        count = _query_transform_latency_count.get(method, 0)
        if count > 0:
            data[f"query_transform_latency_avg_ms_{_metric_key(method)}"] = round(total / count, 2)
    for outcome, count in _mmr_outcomes.items():
        data[f"mmr_total_{_metric_key(outcome)}"] = float(count)
    for outcome, total in _mmr_avg_sim_sum.items():
        count = _mmr_avg_sim_count.get(outcome, 0)
        if count > 0:
            data[f"mmr_avg_pairwise_similarity_{_metric_key(outcome)}"] = round(total / count, 4)
    for (action, sensitivity, bucket), count in _prompt_injection_attempts.items():
        data[
            f"prompt_injection_attempts_{_metric_key(action)}_{_metric_key(sensitivity)}_{_metric_key(bucket)}"
        ] = float(count)
    for (vote, reason), count in _feedback_votes.items():
        data[f"feedback_votes_{_metric_key(vote)}_{_metric_key(reason)}"] = float(count)
    for (direction, bucket), count in _chunk_weight_adjustments.items():
        data[f"chunk_weight_adjustments_{_metric_key(direction)}_{bucket}"] = float(count)
    return data


def get_prometheus_text(*, db: Session | None = None, queue_status=None) -> str:
    if queue_status is not None:
        update_queue_status_snapshot(queue_status)

    document_counts = document_status_counts(db) if db is not None else {}
    processed_documents = document_counts.get("processed", int(_metrics["documents_processed"]))
    failed_documents = document_counts.get("failed", int(_metrics["documents_failed"]))
    lines = [
        "# HELP docuintel_ocr_duration_seconds_total Total OCR processing duration",
        "# TYPE docuintel_ocr_duration_seconds_total counter",
        f"docuintel_ocr_duration_seconds_total {_metrics['ocr_duration_sum']}",
        "",
        "# HELP docuintel_ocr_requests_total Total OCR requests",
        "# TYPE docuintel_ocr_requests_total counter",
        f"docuintel_ocr_requests_total {_metrics['ocr_duration_count']}",
        "",
        "# HELP docuintel_embedding_latency_seconds_total Total embedding latency",
        "# TYPE docuintel_embedding_latency_seconds_total counter",
        f"docuintel_embedding_latency_seconds_total {_metrics['embedding_latency_sum']}",
        "",
        "# HELP docuintel_embedding_requests_total Total embedding requests",
        "# TYPE docuintel_embedding_requests_total counter",
        f"docuintel_embedding_requests_total {_metrics['embedding_latency_count']}",
        "",
        "# HELP docuintel_search_latency_seconds_total Total search latency",
        "# TYPE docuintel_search_latency_seconds_total counter",
        f"docuintel_search_latency_seconds_total {_metrics['search_latency_sum']}",
        "",
        "# HELP docuintel_search_requests_total Total search requests",
        "# TYPE docuintel_search_requests_total counter",
        f"docuintel_search_requests_total {_metrics['search_latency_count']}",
        "",
        "# HELP docuintel_cache_hits_total Cache hits",
        "# TYPE docuintel_cache_hits_total counter",
        f"docuintel_cache_hits_total {_metrics['cache_hits']}",
        "",
        "# HELP docuintel_cache_misses_total Cache misses",
        "# TYPE docuintel_cache_misses_total counter",
        f"docuintel_cache_misses_total {_metrics['cache_misses']}",
        "",
        "# HELP docuintel_documents_processed_total Documents currently processed or processed counter fallback",
        "# TYPE docuintel_documents_processed_total gauge",
        f"docuintel_documents_processed_total {processed_documents}",
        "",
        "# HELP docuintel_documents_failed_total Documents currently failed or failed counter fallback",
        "# TYPE docuintel_documents_failed_total gauge",
        f"docuintel_documents_failed_total {failed_documents}",
        "",
        "# HELP docuintel_embedding_fallbacks_total Embedding fallback generations",
        "# TYPE docuintel_embedding_fallbacks_total counter",
        f"docuintel_embedding_fallbacks_total {_metrics['embedding_fallbacks']}",
        "",
        "# HELP docuintel_watcher_errors_total Watcher ingestion errors",
        "# TYPE docuintel_watcher_errors_total counter",
        f"docuintel_watcher_errors_total {_metrics['watcher_errors']}",
    ]

    if document_counts:
        lines.extend(["", "# HELP docuintel_documents_by_status Documents by status", "# TYPE docuintel_documents_by_status gauge"])
        for status, count in sorted(document_counts.items()):
            lines.append(f'docuintel_documents_by_status{{status="{status}"}} {count}')

    if _queue_pending_by_name:
        lines.extend(["", "# HELP docuintel_jobs_pending_by_queue Pending jobs by queue", "# TYPE docuintel_jobs_pending_by_queue gauge"])
        for queue_name, pending in sorted(_queue_pending_by_name.items()):
            lines.append(f'docuintel_jobs_pending_by_queue{{queue="{queue_name}"}} {pending}')

    if _ocr_cascade_fallbacks:
        lines.extend([
            "",
            "# HELP docuintel_ocr_cascade_fallback_total OCR cascade fallback failures",
            "# TYPE docuintel_ocr_cascade_fallback_total counter",
        ])
        for (engine_name, reason), count in sorted(_ocr_cascade_fallbacks.items()):
            lines.append(
                f'docuintel_ocr_cascade_fallback_total{{engine="{_label(engine_name)}",reason="{_label(reason)}"}} {count}'
            )

    if _ocr_tier_used:
        lines.extend([
            "",
            "# HELP docuintel_ocr_tier_used_total OCR winning tier count",
            "# TYPE docuintel_ocr_tier_used_total counter",
        ])
        for tier, count in sorted(_ocr_tier_used.items()):
            lines.append(f'docuintel_ocr_tier_used_total{{tier="{_label(tier)}"}} {count}')

    if _ocr_tier_by_doc_type:
        lines.extend([
            "",
            "# HELP docuintel_ocr_tier_by_doc_type OCR tier count by document type",
            "# TYPE docuintel_ocr_tier_by_doc_type counter",
        ])
        for (tier, doc_type), count in sorted(_ocr_tier_by_doc_type.items()):
            lines.append(
                f'docuintel_ocr_tier_by_doc_type{{tier="{_label(tier)}",document_type="{_label(doc_type)}"}} {count}'
            )

    if _ocr_dpi_escalations:
        lines.extend([
            "",
            "# HELP docuintel_ocr_dpi_escalation_total DPI ladder escalations (small text re-rendered at higher DPI)",
            "# TYPE docuintel_ocr_dpi_escalation_total counter",
        ])
        for (from_dpi, to_dpi), count in sorted(_ocr_dpi_escalations.items()):
            lines.append(
                f'docuintel_ocr_dpi_escalation_total{{from_dpi="{from_dpi}",to_dpi="{to_dpi}"}} {count}'
            )

    if _ocr_postprocess_corrections:
        lines.extend([
            "",
            "# HELP docuintel_ocr_postprocess_corrections_total Total OCR post-process corrections applied",
            "# TYPE docuintel_ocr_postprocess_corrections_total counter",
            f"docuintel_ocr_postprocess_corrections_total {_ocr_postprocess_corrections}",
        ])

    if _ocr_skip_tier2:
        lines.extend([
            "",
            "# HELP docuintel_ocr_skip_tier2_total Cascade decisions to keep primary instead of replacing with Tier 2",
            "# TYPE docuintel_ocr_skip_tier2_total counter",
        ])
        for reason, count in sorted(_ocr_skip_tier2.items()):
            lines.append(f'docuintel_ocr_skip_tier2_total{{reason="{_label(reason)}"}} {count}')

    if _ocr_language_detected:
        lines.extend([
            "",
            "# HELP docuintel_ocr_language_detected_total Per-page language detections",
            "# TYPE docuintel_ocr_language_detected_total counter",
        ])
        for (lang, doc_type), count in sorted(_ocr_language_detected.items()):
            lines.append(
                f'docuintel_ocr_language_detected_total{{language="{_label(lang)}",document_type="{_label(doc_type)}"}} {count}'
            )

    if _ocr_language_threshold_used:
        lines.extend([
            "",
            "# HELP docuintel_ocr_language_threshold_used Per-language threshold consultations",
            "# TYPE docuintel_ocr_language_threshold_used counter",
        ])
        for (lang, threshold_type), count in sorted(_ocr_language_threshold_used.items()):
            lines.append(
                f'docuintel_ocr_language_threshold_used{{language="{_label(lang)}",threshold_type="{_label(threshold_type)}"}} {count}'
            )

    if _search_strategy_used:
        lines.extend([
            "",
            "# HELP docuintel_search_strategy_used Per-strategy retrieval outcomes",
            "# TYPE docuintel_search_strategy_used counter",
        ])
        for (strategy, outcome), count in sorted(_search_strategy_used.items()):
            lines.append(
                f'docuintel_search_strategy_used{{strategy="{_label(strategy)}",outcome="{_label(outcome)}"}} {count}'
            )

    if _query_transform:
        lines.extend([
            "",
            "# HELP docuintel_query_transform_total Query transformer outcomes",
            "# TYPE docuintel_query_transform_total counter",
        ])
        for (method, outcome), count in sorted(_query_transform.items()):
            lines.append(
                f'docuintel_query_transform_total{{method="{_label(method)}",outcome="{_label(outcome)}"}} {count}'
            )

    if _query_transform_latency_sum:
        lines.extend([
            "",
            "# HELP docuintel_query_transform_latency_avg_ms Average query-transform latency (ms)",
            "# TYPE docuintel_query_transform_latency_avg_ms gauge",
        ])
        for method, total in _query_transform_latency_sum.items():
            count = _query_transform_latency_count.get(method, 0)
            if count > 0:
                avg = total / count
                lines.append(
                    f'docuintel_query_transform_latency_avg_ms{{method="{_label(method)}"}} {avg:.2f}'
                )

    if _mmr_outcomes:
        lines.extend([
            "",
            "# HELP docuintel_mmr_total MMR reranker outcomes",
            "# TYPE docuintel_mmr_total counter",
        ])
        for outcome, count in sorted(_mmr_outcomes.items()):
            lines.append(
                f'docuintel_mmr_total{{outcome="{_label(outcome)}"}} {count}'
            )

    if _mmr_avg_sim_sum:
        lines.extend([
            "",
            "# HELP docuintel_mmr_avg_pairwise_similarity Average pairwise similarity of MMR picks (lower = more diverse)",
            "# TYPE docuintel_mmr_avg_pairwise_similarity gauge",
        ])
        for outcome, total in _mmr_avg_sim_sum.items():
            count = _mmr_avg_sim_count.get(outcome, 0)
            if count > 0:
                avg = total / count
                lines.append(
                    f'docuintel_mmr_avg_pairwise_similarity{{outcome="{_label(outcome)}"}} {avg:.4f}'
                )

    if _prompt_injection_attempts:
        lines.extend([
            "",
            "# HELP docuintel_prompt_injection_attempts Detected prompt-injection attempts in the RAG context",
            "# TYPE docuintel_prompt_injection_attempts counter",
        ])
        for (action, sensitivity, bucket), count in sorted(_prompt_injection_attempts.items()):
            lines.append(
                f'docuintel_prompt_injection_attempts{{action="{_label(action)}",sensitivity="{_label(sensitivity)}",score_bucket="{_label(bucket)}"}} {count}'
            )

    if _feedback_votes:
        lines.extend([
            "",
            "# HELP docuintel_feedback_votes Recorded feedback votes on AI answers",
            "# TYPE docuintel_feedback_votes counter",
        ])
        for (vote, reason), count in sorted(_feedback_votes.items()):
            lines.append(
                f'docuintel_feedback_votes{{vote="{_label(vote)}",reason="{_label(reason)}"}} {count}'
            )

    if _chunk_weight_adjustments:
        lines.extend([
            "",
            "# HELP docuintel_chunk_weight_adjustments Chunk weight adjustments triggered by feedback",
            "# TYPE docuintel_chunk_weight_adjustments counter",
        ])
        for (direction, bucket), count in sorted(_chunk_weight_adjustments.items()):
            lines.append(
                f'docuintel_chunk_weight_adjustments{{direction="{_label(direction)}",source_count_bucket="{bucket}"}} {count}'
            )

    lines.extend([
        "",
        "# HELP docuintel_documents_processed_total Documents processed",
        "# TYPE docuintel_documents_processed_total counter",
        f"docuintel_documents_processed_total {_metrics['documents_processed']}",
        "",
        "# HELP docuintel_documents_failed_total Documents failed",
        "# TYPE docuintel_documents_failed_total counter",
        f"docuintel_documents_failed_total {_metrics['documents_failed']}",
        "",
        "# HELP docuintel_embedding_fallback_total Embedding fallback count",
        "# TYPE docuintel_embedding_fallback_total counter",
        f"docuintel_embedding_fallback_total {_metrics['embedding_fallback_count']}",
        "",
        "# HELP docuintel_watcher_errors_total Watcher ingestion errors",
        "# TYPE docuintel_watcher_errors_total counter",
        f"docuintel_watcher_errors_total {_metrics['watcher_errors']}",
    ])

    # Calculate averages
    if _metrics["ocr_duration_count"] > 0:
        avg = _metrics["ocr_duration_sum"] / _metrics["ocr_duration_count"]
        lines.extend([
            "",
            "# HELP docuintel_ocr_duration_seconds_avg Average OCR duration",
            "# TYPE docuintel_ocr_duration_seconds_avg gauge",
            f"docuintel_ocr_duration_seconds_avg {avg}",
        ])

    if _metrics["embedding_latency_count"] > 0:
        avg = _metrics["embedding_latency_sum"] / _metrics["embedding_latency_count"]
        lines.extend([
            "",
            "# HELP docuintel_embedding_latency_seconds_avg Average embedding latency",
            "# TYPE docuintel_embedding_latency_seconds_avg gauge",
            f"docuintel_embedding_latency_seconds_avg {avg}",
        ])

    if _metrics["search_latency_count"] > 0:
        avg = _metrics["search_latency_sum"] / _metrics["search_latency_count"]
        lines.extend([
            "",
            "# HELP docuintel_search_latency_seconds_avg Average search latency",
            "# TYPE docuintel_search_latency_seconds_avg gauge",
            f"docuintel_search_latency_seconds_avg {avg}",
        ])

    # Cache hit rate
    total_cache = _metrics["cache_hits"] + _metrics["cache_misses"]
    if total_cache > 0:
        hit_rate = _metrics["cache_hits"] / total_cache
        lines.extend([
            "",
            "# HELP docuintel_cache_hit_rate Cache hit rate (0-1)",
            "# TYPE docuintel_cache_hit_rate gauge",
            f"docuintel_cache_hit_rate {hit_rate}",
        ])

    return "\n".join(lines)


def register_metrics_endpoint(app: FastAPI) -> None:
    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=get_prometheus_text(), media_type="text/plain; charset=utf-8")


def _metric_key(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "unknown"


def _label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
