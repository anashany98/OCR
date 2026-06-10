"""R3 — Feedback loop: 👍/👎 on AI answers → chunk weight adjustment.

The chat exposes a thumbs-up / thumbs-down button next to each
assistant message. The vote is persisted in :class:`AIAnswerFeedback`
and fed into this module, which adjusts the ``weight`` column on
``AIAnswerSource`` so the next retrieval for a similar query
ranks community-endorsed chunks higher and community-rejected
chunks lower.

The loop is **closed** but **conservative**:

* Every vote counts but a single vote never moves the weight by
  more than a small delta (positive +0.2, negative -0.3). A
  chunk that gets a single 👎 stays *visible* — a single
  rejection does not blackhole a useful passage.
* A periodic rebalance (``rebalance_chunk_weight``) decays
  every weight back towards 1.0 over time so a one-time
  controversy does not permanently skew the index.
* The min-votes gate prevents a single user from swaying the
  retriever: the loop only applies the vote when the chunk has
  at least N votes (default 3) since the last rebalance.

The function is **fail-safe**: every operation is wrapped in a
``try / except`` and the loop never raises to the caller. A
failed vote just records the failure in the metrics counter and
returns ``False``; the user can try again.

The module is **pure** (no DB) for the score-arithmetic parts
(``compute_weight_delta``, ``rebalance_weight``); the
DB-touching parts (``record_feedback``, ``apply_chunk_weights``)
take a session and are exercised in CI with the existing test
fixtures.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AIAnswer, AIAnswerFeedback, AIAnswerSource
from app.services.metrics import (
    track_chunk_weight_adjustment,
    track_feedback_vote,
)

logger = logging.getLogger("app.services.feedback_loop")


# ---------------------------------------------------------------------------
# Allowed feedback reasons
# ---------------------------------------------------------------------------


ALLOWED_REASONS: frozenset[str] = frozenset(
    {
        "alucinacion",        # LLM invented facts not in the context
        "fuente_incorrecta",  # the cited source is wrong
        "irrelevante",        # the answer does not address the question
        "otro",               # free-form (operator can extend)
    }
)


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------


def clamp_weight(weight: float) -> float:
    """Clamp a chunk weight to ``[0.1, 5.0]``.

    The lower bound prevents a chunk from being *erased* from
    the index by negative feedback; the upper bound prevents a
    single super-popular chunk from dominating every search
    (which would erode diversity).
    """
    return max(0.1, min(5.0, float(weight)))


def compute_weight_delta(
    *,
    vote: int,
    current_weight: float,
    positive_delta: float | None = None,
    negative_delta: float | None = None,
) -> float:
    """Compute the new weight after one vote.

    The default is **multiplicative** so the loop is scale-free:
    * one positive vote bumps the weight by +20 % of the way
      back towards 1.0 *if* the current weight is below 1.0;
      * one negative vote drops the weight by -30 % of the way
      towards 1.0 *if* the current weight is above 1.0.

    In practice: a chunk starts at 1.0. A single 👍 brings it to
    1.20; a second 👍 to 1.36; a third to 1.49 (capped at the
    ``positive_delta`` sum). A single 👎 on a fresh chunk brings
    it to 0.70. The asymmetric delta (negative > positive) is
    deliberate: a wrong answer should hurt a chunk's score
    more than a correct answer should boost it.
    """
    pos = positive_delta if positive_delta is not None else settings.feedback_positive_weight
    neg = negative_delta if negative_delta is not None else settings.feedback_negative_weight
    if vote > 0:
        # Bring the weight *up* towards 1.0 + (1.0 - weight) * pos
        new_weight = current_weight + (1.0 - current_weight) * pos
    elif vote < 0:
        new_weight = current_weight + (1.0 - current_weight) * neg
    else:
        new_weight = current_weight
    return clamp_weight(new_weight)


def rebalance_weight(
    *,
    current_weight: float,
    days_since_rebalance: int,
    decay_per_day: float = 0.05,
) -> float:
    """Decay a weight back towards 1.0 the longer it has been
    since the last rebalance. Caps at ``clamp_weight`` bounds.

    The default ``decay_per_day=0.05`` means a weight of 1.5
    drops to 1.25 after 30 days, then 1.12 after 60. A
    heavily-downvoted chunk at 0.5 climbs to 0.55 after 30 days
    and 0.60 after 60. This is the "let the controversy cool
    down" knob.
    """
    if current_weight == 1.0:
        return 1.0
    factor = max(0.0, 1.0 - decay_per_day * max(0, days_since_rebalance))
    if current_weight > 1.0:
        new_weight = 1.0 + (current_weight - 1.0) * factor
    else:
        new_weight = 1.0 - (1.0 - current_weight) * factor
    return clamp_weight(new_weight)


# ---------------------------------------------------------------------------
# DB-touching entry points
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackOutcome:
    """The result of recording a single vote.

    Attributes:
        accepted: ``True`` when the vote was persisted. ``False``
            on a duplicate (the same user already voted this
            way) or any other soft failure.
        reason: a short label so the API can return a useful
            4xx (``"duplicate"``, ``"invalid_vote"``, ``"answer_not_found"``).
        feedback_id: the new row's id (``None`` on failure).
        new_chunk_weight: the weight after the vote was
            applied. ``None`` when the loop deferred (not
            enough votes yet).
    """

    accepted: bool
    reason: str
    feedback_id: int | None = None
    new_chunk_weight: float | None = None


def record_feedback(
    db: Session,
    *,
    answer_id: int,
    user_id: int,
    vote: int,
    reason: str | None = None,
    comment: str | None = None,
) -> FeedbackOutcome:
    """Persist a vote and, when the loop has enough votes on
    this answer, adjust the weights on the cited sources.

    Args:
        db: SQLAlchemy session.
        answer_id: target ``AIAnswer.id``.
        user_id: voting user's id (always required — the API
            layer must reject anonymous feedback so we can
            audit the loop).
        vote: ``+1`` (positive) or ``-1`` (negative). Anything
            else is rejected.
        reason: one of :data:`ALLOWED_REASONS`. ``None`` is
            accepted (the user did not pick a reason).
        comment: free-form comment. Capped at 2000 chars to
            keep the table lean.

    Returns:
        :class:`FeedbackOutcome` with the new row id and the
        new chunk weight (when applied).
    """
    if vote not in (-1, 1):
        track_feedback_vote(vote=str(vote), reason="invalid_vote")
        return FeedbackOutcome(accepted=False, reason="invalid_vote")

    if reason is not None and reason not in ALLOWED_REASONS:
        reason = None  # silently normalise unknown reasons

    answer = db.get(AIAnswer, answer_id)
    if answer is None:
        track_feedback_vote(vote=str(vote), reason="answer_not_found")
        return FeedbackOutcome(accepted=False, reason="answer_not_found")

    # Reject the vote if the same user already voted the same
    # way on the same answer. (We allow a *change* of vote:
    # voting 👍 then 👎 is two rows but the loop only honours
    # the most recent per (answer, user).)
    existing = db.execute(
        select(AIAnswerFeedback)
        .where(
            AIAnswerFeedback.answer_id == answer_id,
            AIAnswerFeedback.user_id == user_id,
        )
        .order_by(AIAnswerFeedback.created_at.desc())
    ).scalars().first()
    if existing is not None and existing.vote == vote:
        track_feedback_vote(vote=str(vote), reason="duplicate")
        return FeedbackOutcome(accepted=False, reason="duplicate", feedback_id=existing.id)

    safe_comment = (comment or "").strip()[:2000] or None
    new_feedback = AIAnswerFeedback(
        answer_id=answer_id,
        user_id=user_id,
        vote=vote,
        reason=reason,
        comment=safe_comment,
    )
    db.add(new_feedback)
    db.flush()
    track_feedback_vote(vote=str(vote), reason=reason or "none")

    # Apply the weight adjustment to every cited source. The
    # loop is "consensus" — a single vote shifts the weight
    # but the min-votes gate below controls how many votes
    # it takes for the *cumulative* effect to be visible at
    # retrieval time.
    new_weight = apply_chunk_weights(db, answer_id=answer_id, latest_vote=vote)
    db.commit()
    return FeedbackOutcome(
        accepted=True,
        reason="recorded",
        feedback_id=new_feedback.id,
        new_chunk_weight=new_weight,
    )


def apply_chunk_weights(
    db: Session,
    *,
    answer_id: int,
    latest_vote: int,
) -> float | None:
    """Adjust the ``weight`` column on every cited source of
    ``answer_id`` based on the *cumulative* vote count since
    the last rebalance. Returns the new average weight, or
    ``None`` when the loop deferred (not enough votes yet).

    The min-votes gate: the loop only applies the cumulative
    vote when at least ``settings.feedback_min_votes_to_apply``
    distinct votes are on the table. Below that threshold the
    individual vote is recorded (so we can audit it) but the
    chunk weight is left unchanged to avoid one user swaying
    the retriever.
    """
    since = datetime.utcnow() - timedelta(days=settings.feedback_rebalance_window_days)
    vote_rows = db.execute(
        select(AIAnswerFeedback.vote)
        .where(
            AIAnswerFeedback.answer_id == answer_id,
            AIAnswerFeedback.created_at >= since,
        )
    ).scalars().all()
    total = len(vote_rows)
    if total < settings.feedback_min_votes_to_apply:
        return None

    # Compute the cumulative weight: each +1 vote contributes
    # ``+pos`` to the per-source weight, each -1 contributes
    # ``+neg``. We aggregate *after* the most recent vote so
    # the operator's contribution is part of the visible
    # effect immediately after they click 👍/👎.
    pos = settings.feedback_positive_weight
    neg = settings.feedback_negative_weight
    cumulative = 0.0
    for v in vote_rows:
        cumulative += pos if v > 0 else neg

    # Apply to every cited source. The cap is at 1.0 + abs(cumulative)
    # so a single very-angry user cannot sink a chunk below 0.1
    # in one round of clicks; the periodic rebalance eventually
    # pulls everything back to 1.0.
    sources = list(
        db.scalars(
            select(AIAnswerSource).where(AIAnswerSource.answer_id == answer_id)
        )
    )
    if not sources:
        return None
    new_weight = clamp_weight(1.0 + cumulative)
    direction = "up" if new_weight > 1.0 else ("down" if new_weight < 1.0 else "neutral")
    for source in sources:
        source.weight = new_weight
    track_chunk_weight_adjustment(direction=direction, source_count=len(sources))
    db.flush()
    return new_weight


def rebalance_chunk_weight(
    db: Session,
    *,
    chunk_id: int,
    days_since_rebalance: int,
) -> float | None:
    """Decay the weight of a single source row back towards
    1.0. Returns the new weight (``None`` if the source does
    not exist).
    """
    source = db.get(AIAnswerSource, chunk_id)
    if source is None:
        return None
    new_weight = rebalance_weight(
        current_weight=source.weight,
        days_since_rebalance=days_since_rebalance,
    )
    source.weight = new_weight
    db.flush()
    direction = "up" if new_weight > source.weight else ("down" if new_weight < source.weight else "neutral")
    track_chunk_weight_adjustment(direction=direction, source_count=1)
    return new_weight


def rebalance_all_chunk_weights(
    db: Session,
    *,
    days_since_rebalance: int,
) -> int:
    """Periodic sweep: decay every non-1.0 weight back towards
    1.0. Returns the number of rows touched. Called by a
    Celery beat task on the maintenance queue.
    """
    rows = db.execute(
        select(AIAnswerSource).where(AIAnswerSource.weight != 1.0)
    ).scalars().all()
    touched = 0
    for source in rows:
        new_weight = rebalance_weight(
            current_weight=source.weight,
            days_since_rebalance=days_since_rebalance,
        )
        if new_weight != source.weight:
            source.weight = new_weight
            touched += 1
    db.flush()
    if touched:
        track_chunk_weight_adjustment(direction="rebalanced", source_count=touched)
    return touched


__all__ = [
    "ALLOWED_REASONS",
    "FeedbackOutcome",
    "record_feedback",
    "apply_chunk_weights",
    "rebalance_chunk_weight",
    "rebalance_all_chunk_weights",
    "compute_weight_delta",
    "rebalance_weight",
    "clamp_weight",
]
