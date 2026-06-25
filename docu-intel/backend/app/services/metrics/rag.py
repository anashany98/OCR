"""RAG / chat metrics: query transformer, MMR, prompt-injection, feedback."""

from __future__ import annotations

from ._registry import (
    CHUNK_WEIGHT_ADJUSTMENTS,
    FEEDBACK_VOTES,
    MMR_AVG_PAIRWISE_SIMILARITY,
    MMR_OUTCOMES,
    PROMPT_INJECTION_ATTEMPTS,
    QUERY_TRANSFORM,
    QUERY_TRANSFORM_LATENCY,
)

# ---------------------------------------------------------------------------
# Query transformer (R1)
# ---------------------------------------------------------------------------


def track_query_transform(
    method: str,
    outcome: str,
    *,
    latency_ms: int = 0,
) -> None:
    """Record a query-transformer call.

    ``method`` is the strategy requested (``"hyde"``,
    ``"multi_query"``, ``"auto"`` after resolution, or ``"off"``).
    ``outcome`` is ``"success" | "fallback" | "disabled"``.
    ``latency_ms`` is the wall-clock time spent in the LLM call.
    """
    clean_method = (method or "unknown").lower().strip() or "unknown"
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    QUERY_TRANSFORM.labels(method=clean_method, outcome=clean_outcome).inc()
    if latency_ms and latency_ms > 0:
        QUERY_TRANSFORM_LATENCY.labels(method=clean_method).observe(latency_ms)


# ---------------------------------------------------------------------------
# MMR (E5)
# ---------------------------------------------------------------------------


def track_mmr(outcome: str, *, avg_similarity: float = 0.0) -> None:
    """Record a Maximal Marginal Relevance rerank call.

    ``outcome`` is one of ``"diversified" | "passthrough" |
    "passthrough_lambda_one" | "empty"``. ``avg_similarity`` is
    the running mean of the n-gram Jaccard similarity between
    chosen hits; we keep it as a gauge so the admin UI can show
    how diverse the picks really are.
    """
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    MMR_OUTCOMES.labels(outcome=clean_outcome).inc()
    if avg_similarity and avg_similarity >= 0.0:
        # We update the gauge to the cumulative mean of the
        # values seen so far. The caller can override with a
        # ``refresh_mmr_avg_similarity_gauge`` call if they keep
        # a more precise running mean themselves.
        current_count = MMR_OUTCOMES.labels(outcome=clean_outcome)._value.get()
        previous_sum = MMR_AVG_PAIRWISE_SIMILARITY.labels(outcome=clean_outcome)._value.get() * max(
            current_count - 1, 0
        )
        new_sum = previous_sum + float(avg_similarity)
        MMR_AVG_PAIRWISE_SIMILARITY.labels(outcome=clean_outcome).set(
            new_sum / max(current_count, 1)
        )


# ---------------------------------------------------------------------------
# Prompt-injection (R2)
# ---------------------------------------------------------------------------


def track_prompt_injection_attempts(
    *,
    action: str,
    sensitivity: str,
    score_bucket: str,
) -> None:
    """Record a prompt-injection attempt detected by
    :mod:`app.services.prompt_sanitizer`.

    ``action`` is the action taken (``"logged" | "sanitised" |
    "dropped"``). ``sensitivity`` is the operator-chosen
    threshold. ``score_bucket`` keeps the label set small.
    """
    PROMPT_INJECTION_ATTEMPTS.labels(
        action=(action or "unknown").lower().strip() or "unknown",
        sensitivity=(sensitivity or "unknown").lower().strip() or "unknown",
        score_bucket=(score_bucket or "unknown").lower().strip() or "unknown",
    ).inc()


# ---------------------------------------------------------------------------
# Feedback loop (R3)
# ---------------------------------------------------------------------------


def track_feedback_vote(*, vote: str, reason: str) -> None:
    """Record a 👍/👎 vote on an AI answer.

    ``vote`` is the string form of ``+1`` or ``-1``; ``reason``
    is one of the allowed reasons or ``"none"`` / ``"duplicate"``
    / ``"invalid_vote"`` / ``"answer_not_found"`` for the
    bookkeeping outcomes.
    """
    FEEDBACK_VOTES.labels(
        vote=(vote or "unknown").strip() or "unknown",
        reason=(reason or "none").strip().lower() or "none",
    ).inc()


def track_chunk_weight_adjustment(*, direction: str, source_count: int) -> None:
    """Record a chunk-weight adjustment.

    ``direction`` is one of ``"up" | "down" | "neutral" |
    "rebalanced"``. ``source_count`` is bucketed into
    ``"1" | "2_5" | "6_20" | "21_plus"`` to keep the cardinality
    bounded.
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
    CHUNK_WEIGHT_ADJUSTMENTS.labels(
        direction=clean_direction,
        source_count_bucket=bucket,
    ).inc()
