"""Embedding metrics: per-model latency and fallback counter.

Keeps the public ``track_*`` API the rest of the codebase
already calls. Bumps the embedding histogram and the
fallback counter; the cache hit-rate gauge lives in
``search.py`` (the cache layer is shared between embedding and
search callers).
"""

from __future__ import annotations

from ._registry import EMBEDDING_DURATION, EMBEDDING_FALLBACKS


def track_embedding_latency(
    duration: float,
    *,
    model: str | None = None,
) -> None:
    """Record the wall-clock duration of one embedding call.

    ``model`` is the embedding model name (e.g. ``"bge-m3"``).
    It is optional: when the caller does not know the model at the
    point of recording, the metric lands in the ``"unknown"``
    bucket.
    """
    if duration < 0:
        return
    EMBEDDING_DURATION.labels(
        model=(model or "unknown").strip() or "unknown",
    ).observe(duration)


# Backward-compatible alias: the original module exported this
# name; some callers (and tests) still import it as such.
track_embedding_duration = track_embedding_latency


def track_embedding_fallback(count: int = 1) -> None:
    """Record that the embedding layer fell back to the hash-based
    stub because the real model was unavailable."""
    if count <= 0:
        return
    EMBEDDING_FALLBACKS.inc(count)
