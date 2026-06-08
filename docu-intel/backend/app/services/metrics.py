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


def track_ocr_duration(duration: float) -> None:
    _metrics["ocr_duration_sum"] += duration
    _metrics["ocr_duration_count"] += 1


def track_ocr_cascade_fallback(engine_name: str, reason: str) -> None:
    key = (engine_name or "unknown", reason or "unknown")
    _ocr_cascade_fallbacks[key] = _ocr_cascade_fallbacks.get(key, 0) + 1


def track_ocr_tier_used(tier: str) -> None:
    clean_tier = tier or "unknown"
    _ocr_tier_used[clean_tier] = _ocr_tier_used.get(clean_tier, 0) + 1


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
