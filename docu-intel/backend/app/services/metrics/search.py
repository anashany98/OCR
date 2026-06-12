"""Search metrics: per-strategy latency, strategy/outcome, cache."""

from __future__ import annotations

from ._registry import (
    CACHE_HIT_RATE,
    CACHE_HITS,
    CACHE_MISSES,
    SEARCH_DURATION,
    SEARCH_STRATEGY_USED,
)


def track_search_latency(
    duration: float,
    *,
    strategy: str | None = None,
) -> None:
    """Record the wall-clock duration of one search call.

    ``strategy`` is the search strategy that won (``"bm25"``,
    ``"cosine"``, ``"text"``, ``"hybrid"``). When ``None`` the
    metric lands in the ``"unknown"`` bucket.
    """
    if duration < 0:
        return
    SEARCH_DURATION.labels(
        strategy=(strategy or "unknown").lower().strip() or "unknown",
    ).observe(duration)


def track_search_strategy_used(strategy: str, outcome: str) -> None:
    """Record which retrieval strategy was used (and how).

    ``strategy`` is one of ``"bm25" | "cosine" | "text" | "hybrid"``.
    ``outcome`` is ``"executed" | "failed" | "skipped_non_postgres"``.
    """
    SEARCH_STRATEGY_USED.labels(
        strategy=(strategy or "unknown").lower().strip() or "unknown",
        outcome=(outcome or "unknown").lower().strip() or "unknown",
    ).inc()


def track_cache_hit() -> None:
    CACHE_HITS.inc()


def track_cache_miss() -> None:
    CACHE_MISSES.inc()


def update_cache_hit_rate() -> None:
    """Refresh the ``docuintel_cache_hit_rate`` gauge from the
    current counter values.

    Counters are monotonic so we cannot compute a "rolling"
    hit-rate inside the counter itself; instead we expose a
    gauge and update it whenever the operator scrapes
    ``/metrics``.
    """
    total = CACHE_HITS._value.get() + CACHE_MISSES._value.get()
    if total == 0:
        CACHE_HIT_RATE.set(0.0)
        return
    CACHE_HIT_RATE.set(CACHE_HITS._value.get() / total)
