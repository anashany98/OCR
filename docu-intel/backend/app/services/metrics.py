from __future__ import annotations

import time
from functools import wraps
from typing import Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

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
}


def track_ocr_duration(duration: float) -> None:
    _metrics["ocr_duration_sum"] += duration
    _metrics["ocr_duration_count"] += 1


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


def get_metrics() -> dict[str, float]:
    return _metrics.copy()


def get_prometheus_text() -> str:
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
    ]

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