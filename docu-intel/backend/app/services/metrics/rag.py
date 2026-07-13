"""RAG / chat metrics: query transformer, MMR, prompt-injection, feedback."""

from __future__ import annotations

from ._registry import (
    AI_SOURCE_STALE_BLOCK,
    AI_STREAM_PERSIST_FAILURE,
    ANSWERS_WITHOUT_SOURCES,
    CHAT_CACHE_LOOKUP,
    CHAT_CACHE_LOOKUP_LATENCY,
    CHAT_RETRIEVAL_DURATION,
    CHAT_RETRIEVAL_OUTCOME,
    CHAT_STAGE_DURATION,
    CHAT_STAGE_OUTCOME,
    CHAT_STREAM_FIRST_EVENT,
    CHAT_STREAM_TOTAL,
    CHUNK_WEIGHT_ADJUSTMENTS,
    FEEDBACK_VOTES,
    FOLLOWUP_RESOLUTION,
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


# ---------------------------------------------------------------------------
# CR1 — AI source persistence
# ---------------------------------------------------------------------------


def track_ai_source_stale_block() -> None:
    """Record that an AIAnswerSource was saved with block_id=NULL
    because the referenced DocumentBlock no longer exists."""
    AI_SOURCE_STALE_BLOCK.inc()


def track_ai_stream_persist_failure(stage: str) -> None:
    """Record a failure during AI stream answer persistence.

    ``stage`` is one of ``"answer" | "sources" | "context" | "cache"``.
    """
    clean_stage = (stage or "unknown").lower().strip() or "unknown"
    AI_STREAM_PERSIST_FAILURE.labels(stage=clean_stage).inc()


# ---------------------------------------------------------------------------
# CR3 — Follow-up resolution
# ---------------------------------------------------------------------------


def track_followup_resolution(kind: str, outcome: str) -> None:
    """Record a follow-up question resolution attempt.

    ``kind`` is the detected reference type (``"pronoun" | "ellipsis" |
    "explicit" | "none"``). ``outcome`` is ``"resolved" | "no_context" |
    "ambiguous" | "global"``.
    """
    clean_kind = (kind or "none").lower().strip() or "none"
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    FOLLOWUP_RESOLUTION.labels(kind=clean_kind, outcome=clean_outcome).inc()


# ---------------------------------------------------------------------------
# CR8 — Answers without sources
# ---------------------------------------------------------------------------


def track_answer_without_source(reason: str) -> None:
    """Record an AI answer persisted without any cited source.

    ``reason`` is one of ``"no_context" | "fallback" | "error" |
    "all_stale"``.
    """
    clean_reason = (reason or "unknown").lower().strip() or "unknown"
    ANSWERS_WITHOUT_SOURCES.labels(reason=clean_reason).inc()


# ---------------------------------------------------------------------------
# MiniMax M3 — chat path stage instrumentation
# ---------------------------------------------------------------------------
# Use ``track_chat_stage`` as a context manager so a slow stage is
# recorded even when the surrounding code raises. Outcomes are
# ``"ok" | "empty" | "error" | "skipped"``. The stage label set is
# fixed to keep cardinality bounded; pass one of the values listed in
# the docstring of ``_ALLOWED_STAGES``.
# ---------------------------------------------------------------------------


_ALLOWED_STAGES = frozenset(
    {
        "reference_resolution",
        "tool_selection",
        "scope_enforcement",
        "context_collection",
        "confidence_gates",
        "memory_block",
        "grounded_response",
        "source_sanitization",
        "persistence",
        "cache_lookup",
        "cache_write",
    }
)


def track_chat_stage(stage: str) -> "ChatStageTimer":
    """Return a context manager that records the wall-clock duration
    of ``stage`` and tags the outcome on exit.

    Usage::

        with track_chat_stage("context_collection") as timer:
            items = collect_context(...)
            timer.set_outcome("ok" if items else "empty")
    """
    if stage not in _ALLOWED_STAGES:
        # Defensive: drop unknown stages into a single bucket so a
        # typo cannot blow up the metric cardinality.
        stage = "other"
    return ChatStageTimer(stage)


class ChatStageTimer:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.outcome = "ok"
        self._t0: float = 0.0
        self._recorded = False

    def set_outcome(self, outcome: str) -> None:
        self.outcome = (outcome or "unknown").lower().strip() or "unknown"

    def __enter__(self) -> "ChatStageTimer":
        import time as _time

        self._t0 = _time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        import time as _time

        if self._recorded:
            return
        self._recorded = True
        elapsed = max(_time.perf_counter() - self._t0, 0.0)
        # An exception always wins over an explicit outcome.
        if exc is not None:
            self.outcome = "error"
        try:
            CHAT_STAGE_DURATION.labels(stage=self.stage).observe(elapsed)
            CHAT_STAGE_OUTCOME.labels(stage=self.stage, outcome=self.outcome).inc()
        except Exception:  # pragma: no cover - metrics must never raise
            pass


def track_chat_retrieval(strategy: str, outcome: str, *, latency_ms: int = 0) -> None:
    """Record a retrieval sub-path. ``strategy`` is one of the bounded
    set documented on :data:`CHAT_RETRIEVAL_DURATION`. ``outcome`` is
    ``hit | miss | skipped | error``."""
    clean_strategy = (strategy or "unknown").lower().strip() or "unknown"
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    CHAT_RETRIEVAL_OUTCOME.labels(strategy=clean_strategy, outcome=clean_outcome).inc()
    if latency_ms and latency_ms > 0:
        CHAT_RETRIEVAL_DURATION.labels(strategy=clean_strategy).observe(latency_ms / 1000.0)


def track_chat_cache_lookup(kind: str, outcome: str, *, latency_ms: int = 0) -> None:
    """Record an AI cache lookup. ``kind`` is ``exact`` or ``semantic``;
    ``outcome`` is ``hit | miss | error | disabled``."""
    clean_kind = (kind or "unknown").lower().strip() or "unknown"
    clean_outcome = (outcome or "unknown").lower().strip() or "unknown"
    CHAT_CACHE_LOOKUP.labels(kind=clean_kind, outcome=clean_outcome).inc()
    if latency_ms and latency_ms >= 0:
        CHAT_CACHE_LOOKUP_LATENCY.labels(kind=clean_kind).observe(latency_ms / 1000.0)


def track_chat_stream_event(event: str, *, latency_ms: float) -> None:
    """Record the time of an SSE event relative to the request start.

    ``event`` is one of ``start | delta | end | error``. Only the
    cumulative latency to that event is recorded — no event payload.
    """
    clean_event = (event or "other").lower().strip() or "other"
    if latency_ms and latency_ms > 0:
        CHAT_STREAM_FIRST_EVENT.labels(event=clean_event).observe(latency_ms / 1000.0)


def track_chat_stream_total(*, latency_ms: float) -> None:
    """Record the total wall-clock duration of a stream call."""
    if latency_ms and latency_ms > 0:
        CHAT_STREAM_TOTAL.observe(latency_ms / 1000.0)
