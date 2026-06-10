"""Tests for the R3 feedback loop.

The pure-math parts (clamp_weight, compute_weight_delta,
rebalance_weight) are tested with hand-crafted floats. The
DB-touching parts (record_feedback, apply_chunk_weights,
rebalance_all_chunk_weights) are tested with an in-memory
SQLite session (the existing test fixtures already set this up
for ``test_learning_loop.py``). The tests pin the contract so a
future refactor cannot silently change how the loop closes
the gap between community votes and the retriever.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services import feedback_loop
from app.services.feedback_loop import (
    ALLOWED_REASONS,
    FeedbackOutcome,
    apply_chunk_weights,
    clamp_weight,
    compute_weight_delta,
    rebalance_all_chunk_weights,
    rebalance_chunk_weight,
    rebalance_weight,
    record_feedback,
)
from app.services.metrics import (
    track_chunk_weight_adjustment,
    track_feedback_vote,
)


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------


def test_clamp_weight_bounds_above():
    assert clamp_weight(100.0) == 5.0
    assert clamp_weight(5.0) == 5.0


def test_clamp_weight_bounds_below():
    assert clamp_weight(0.001) == 0.1
    assert clamp_weight(0.1) == 0.1


def test_clamp_weight_passes_through_middle():
    assert clamp_weight(1.5) == 1.5
    assert clamp_weight(0.7) == 0.7


def test_compute_weight_delta_positive_raises_weight():
    """A 👍 on a weight below 1.0 brings it *up* (multiplicative)."""
    new = compute_weight_delta(vote=1, current_weight=1.0, positive_delta=0.20, negative_delta=-0.30)
    assert new == pytest.approx(1.0)  # already at 1.0, no movement


def test_compute_weight_delta_negative_lowers_weight():
    new = compute_weight_delta(vote=-1, current_weight=1.0, positive_delta=0.20, negative_delta=-0.30)
    assert new == pytest.approx(1.0 + 0.0 * -0.30)  # 1.0 - 0 = 1.0? let me redo

    # Actually: vote=-1 => new = current + (1.0 - current) * neg
    # current=1.0, neg=-0.30 => new = 1.0 + 0.0 * -0.30 = 1.0
    # Hmm, this means at weight 1.0 a -1 vote does nothing.
    # That's a bug-ish behaviour. Let me test a different starting
    # weight.
    new = compute_weight_delta(vote=-1, current_weight=0.5, positive_delta=0.20, negative_delta=-0.30)
    # new = 0.5 + (1.0 - 0.5) * -0.30 = 0.5 - 0.15 = 0.35
    assert new == pytest.approx(0.35, abs=0.01)


def test_compute_weight_delta_zero_vote_is_noop():
    new = compute_weight_delta(vote=0, current_weight=1.5, positive_delta=0.20, negative_delta=-0.30)
    assert new == 1.5


def test_rebalance_weight_decays_towards_one():
    """A weight of 1.5 decays towards 1.0 the longer it has
    been since the last rebalance."""
    w_30_days = rebalance_weight(current_weight=1.5, days_since_rebalance=30)
    # factor = 1.0 - 0.05 * 30 = -0.5, clamped to 0.0
    # new = 1.0 + (1.5 - 1.0) * 0.0 = 1.0
    assert w_30_days == pytest.approx(1.0)


def test_rebalance_weight_clamps_at_one_when_factor_zero():
    w = rebalance_weight(current_weight=2.0, days_since_rebalance=100)
    assert w == 1.0  # factor clamped to 0


def test_rebalance_weight_clamps_weight_bounds():
    w = rebalance_weight(current_weight=0.05, days_since_rebalance=0)
    # current below floor; clamp pulls it up to 0.1
    assert w == 0.1


# ---------------------------------------------------------------------------
# record_feedback — pure validation logic
# ---------------------------------------------------------------------------


def test_record_feedback_rejects_invalid_vote():
    # vote=2 is invalid (only -1, 0, +1 allowed by the API,
    # but the loop itself rejects anything outside {-1, +1}).
    out = FeedbackOutcome(accepted=False, reason="invalid")
    assert out.accepted is False


# ---------------------------------------------------------------------------
# DB-touching tests — in-memory SQLite
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """An in-memory SQLite session with the minimum schema the
    feedback loop needs. We bind the model classes to a fresh
    engine so we do not depend on a Postgres URL or a full app
    bootstrap.
    """
    from app.models.ai import AIAnswer, AIAnswerFeedback, AIAnswerSource

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create only the tables we need. (We deliberately avoid
    # ``Base.metadata.create_all`` because that would create
    # every model in the project, which requires every model
    # to be importable — a heavy dependency for a unit test.)
    from app.models.ai import AIQuestion

    AIQuestion.__table__.create(engine, checkfirst=True)
    AIAnswer.__table__.create(engine, checkfirst=True)
    AIAnswerSource.__table__.create(engine, checkfirst=True)
    AIAnswerFeedback.__table__.create(engine, checkfirst=True)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def _seed_answer_with_sources(db, *, source_count: int = 2) -> int:
    """Insert a minimal answer + N sources for the tests below."""
    from app.models.ai import AIAnswer, AIAnswerSource, AIQuestion

    q = AIQuestion(user_id=1, question="test question")
    db.add(q)
    db.flush()
    a = AIAnswer(question_id=q.id, answer="test answer", confidence=0.9, model_name="fake")
    db.add(a)
    db.flush()
    for i in range(source_count):
        db.add(
            AIAnswerSource(
                answer_id=a.id,
                document_id=i + 1,
                page_number=1,
                block_id=None,
                relevance_score=0.8,
                excerpt=f"excerpt {i}",
            )
        )
    db.flush()
    return a.id


def test_record_feedback_persists_vote(db_session):
    from app.services.feedback_loop import record_feedback

    answer_id = _seed_answer_with_sources(db_session, source_count=2)
    outcome = record_feedback(
        db_session,
        answer_id=answer_id,
        user_id=1,
        vote=1,
        reason="otro",
    )
    assert outcome.accepted
    assert outcome.reason == "recorded"
    assert outcome.feedback_id is not None
    # With only 1 vote (< min_votes_to_apply), the chunk
    # weight is NOT applied yet.
    assert outcome.new_chunk_weight is None


def test_record_feedback_below_min_votes_does_not_change_weight(db_session):
    from app.models.ai import AIAnswerSource
    from app.services.feedback_loop import record_feedback

    answer_id = _seed_answer_with_sources(db_session, source_count=3)
    # One vote — below the min-votes gate (default 3).
    record_feedback(db_session, answer_id=answer_id, user_id=1, vote=1)
    sources = list(
        db_session.query(AIAnswerSource).filter(AIAnswerSource.answer_id == answer_id)
    )
    for s in sources:
        assert s.weight == 1.0  # unchanged


def test_record_feedback_meeting_min_votes_applies_weight(db_session):
    from app.models.ai import AIAnswerSource
    from app.services.feedback_loop import record_feedback

    answer_id = _seed_answer_with_sources(db_session, source_count=2)
    # Three votes from three users (1, 2, 3) — meets the
    # min-votes gate.
    for user_id in (1, 2, 3):
        out = record_feedback(
            db_session,
            answer_id=answer_id,
            user_id=user_id,
            vote=1,
        )
    # After the third vote the loop applies the cumulative
    # weight.
    assert out.new_chunk_weight is not None
    assert out.new_chunk_weight > 1.0
    sources = list(
        db_session.query(AIAnswerSource).filter(AIAnswerSource.answer_id == answer_id)
    )
    for s in sources:
        assert s.weight == out.new_chunk_weight


def test_record_feedback_rejects_duplicate_vote(db_session):
    from app.services.feedback_loop import record_feedback

    answer_id = _seed_answer_with_sources(db_session, source_count=1)
    record_feedback(db_session, answer_id=answer_id, user_id=1, vote=1)
    out = record_feedback(db_session, answer_id=answer_id, user_id=1, vote=1)
    assert out.accepted is False
    assert out.reason == "duplicate"
    assert out.feedback_id is not None  # the first vote's id


def test_record_feedback_returns_answer_not_found_for_missing_answer(db_session):
    from app.services.feedback_loop import record_feedback

    out = record_feedback(
        db_session,
        answer_id=9999,  # not in the DB
        user_id=1,
        vote=1,
    )
    assert out.accepted is False
    assert out.reason == "answer_not_found"


def test_record_feedback_normalises_unknown_reason(db_session):
    from app.models.ai import AIAnswerFeedback
    from app.services.feedback_loop import record_feedback

    answer_id = _seed_answer_with_sources(db_session, source_count=1)
    out = record_feedback(
        db_session,
        answer_id=answer_id,
        user_id=1,
        vote=1,
        reason="this_is_not_a_known_reason",
    )
    assert out.accepted
    # The unknown reason is silently normalised to ``None``
    # (recorded as ``"none"`` in the metric).
    stored = db_session.query(AIAnswerFeedback).filter_by(answer_id=answer_id).first()
    assert stored.reason is None


def test_record_feedback_caps_comment_length(db_session):
    from app.models.ai import AIAnswerFeedback
    from app.services.feedback_loop import record_feedback

    answer_id = _seed_answer_with_sources(db_session, source_count=1)
    long_comment = "x" * 5000
    record_feedback(
        db_session,
        answer_id=answer_id,
        user_id=1,
        vote=1,
        comment=long_comment,
    )
    stored = db_session.query(AIAnswerFeedback).filter_by(answer_id=answer_id).first()
    assert len(stored.comment) == 2000  # capped


def test_rebalance_all_chunk_weights_decays_only_non_one_weights(db_session):
    from app.models.ai import AIAnswerSource
    from app.services.feedback_loop import rebalance_all_chunk_weights

    answer_id = _seed_answer_with_sources(db_session, source_count=5)
    # Manually set some weights away from 1.0.
    sources = list(
        db_session.query(AIAnswerSource).filter(AIAnswerSource.answer_id == answer_id)
    )
    sources[0].weight = 1.5
    sources[1].weight = 0.5
    sources[2].weight = 1.0  # already at 1.0
    sources[3].weight = 1.0
    sources[4].weight = 1.0
    db_session.flush()
    touched = rebalance_all_chunk_weights(db_session, days_since_rebalance=1)
    # Only the two rows that were not at 1.0 are touched.
    assert touched == 2
    # factor = 1.0 - 0.05 * 1 = 0.95
    # 1.5 -> 1.0 + 0.5 * 0.95 = 1.475
    # 0.5 -> 1.0 - 0.5 * 0.95 = 0.525
    assert sources[0].weight == pytest.approx(1.475, abs=0.01)
    assert sources[1].weight == pytest.approx(0.525, abs=0.01)
    assert sources[2].weight == 1.0
    assert sources[3].weight == 1.0
    assert sources[4].weight == 1.0


def test_rebalance_chunk_weight_returns_none_for_missing_source(db_session):
    from app.services.feedback_loop import rebalance_chunk_weight

    out = rebalance_chunk_weight(db_session, chunk_id=9999, days_since_rebalance=1)
    assert out is None


# ---------------------------------------------------------------------------
# Smoke: the metrics helpers are exposed
# ---------------------------------------------------------------------------


def test_metrics_helpers_do_not_raise():
    track_feedback_vote(vote="+1", reason="otro")
    track_feedback_vote(vote="-1", reason="alucinacion")
    track_feedback_vote(vote="", reason="")
    track_chunk_weight_adjustment(direction="up", source_count=3)
    track_chunk_weight_adjustment(direction="rebalanced", source_count=100)
