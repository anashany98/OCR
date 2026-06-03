"""Tests for the learning loop health monitoring and stale auto-rejection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base
from app.models import ClassificationSuggestion, LearnedPattern
from app.services import learning_health


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_suggestion(
    db,
    *,
    status: str = "pending",
    created_at: datetime | None = None,
    client_id: int | None = 1,
    suggestion_type: str = "classification_correction",
    reason: str = "agent says so",
) -> ClassificationSuggestion:
    s = ClassificationSuggestion(
        document_id=1,
        integration_client_id=client_id,
        suggestion_type=suggestion_type,
        confidence=0.7,
        reason=reason,
        status=status,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# mark_stale_suggestions
# ---------------------------------------------------------------------------


def test_mark_stale_sets_field_on_old_pending(db, monkeypatch):
    """Pending rows older than the threshold get stale_at set."""
    monkeypatch.setattr(settings, "learning_stale_pending_days", 7)
    old = _make_suggestion(
        db,
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    fresh = _make_suggestion(
        db,
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    marked = learning_health.mark_stale_suggestions(db)
    assert marked == 1
    db.expire_all()
    db.refresh(old)
    db.refresh(fresh)
    assert old.stale_at is not None
    assert fresh.stale_at is None


def test_mark_stale_skips_non_pending(db, monkeypatch):
    """Approved/rejected/applied rows are not touched even if old."""
    monkeypatch.setattr(settings, "learning_stale_pending_days", 7)
    old = _make_suggestion(
        db,
        status="approved",
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    marked = learning_health.mark_stale_suggestions(db)
    assert marked == 0
    db.refresh(old)
    assert old.stale_at is None


def test_mark_stale_disabled_when_threshold_zero(db):
    """Setting the threshold to 0 disables the feature."""
    import app.services.learning_health as lh

    original = settings.learning_stale_pending_days
    object.__setattr__(settings, "learning_stale_pending_days", 0)
    try:
        assert lh.mark_stale_suggestions(db) == 0
    finally:
        object.__setattr__(settings, "learning_stale_pending_days", original)


# ---------------------------------------------------------------------------
# auto_reject_stale_suggestions
# ---------------------------------------------------------------------------


def test_auto_reject_moves_stale_to_rejected(db, monkeypatch):
    """Stale rows are flipped to status='rejected' with a reason suffix."""
    monkeypatch.setattr(settings, "learning_stale_pending_days", 7)
    _make_suggestion(
        db,
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )

    result = learning_health.auto_reject_stale_suggestions(db)
    assert result["rejected"] == 1

    pending = db.scalar(_count_stmt("pending"))
    rejected = db.scalar(_count_stmt("rejected"))
    assert pending == 0
    assert rejected == 1

    rejected_row = db.scalar(_all_suggestions().where(ClassificationSuggestion.status == "rejected"))
    assert "[auto-rejected" in (rejected_row.reason or "")


def test_auto_reject_returns_remaining_count(db, monkeypatch):
    """The 'remaining' field reflects how many pending rows are left after the run."""
    monkeypatch.setattr(settings, "learning_stale_pending_days", 7)
    _make_suggestion(db, created_at=datetime.now(timezone.utc) - timedelta(days=30))
    _make_suggestion(db, created_at=datetime.now(timezone.utc) - timedelta(days=30))
    # fresh one stays pending
    _make_suggestion(db, created_at=datetime.now(timezone.utc) - timedelta(days=1))

    result = learning_health.auto_reject_stale_suggestions(db)
    assert result["rejected"] == 2
    assert result["remaining"] == 1


# ---------------------------------------------------------------------------
# client_recent_pending_count
# ---------------------------------------------------------------------------


def test_client_recent_pending_count_filters_to_window(db, monkeypatch):
    """Only rows in the last ``window_seconds`` are counted."""
    monkeypatch.setattr(settings, "learning_per_client_window_seconds", 3600)
    _make_suggestion(
        db,
        client_id=7,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=60),
    )
    _make_suggestion(
        db,
        client_id=7,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    _make_suggestion(
        db,
        client_id=8,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=60),
    )
    assert learning_health.client_recent_pending_count(db, 7) == 1
    assert learning_health.client_recent_pending_count(db, 8) == 1


# ---------------------------------------------------------------------------
# health_snapshot
# ---------------------------------------------------------------------------


def test_health_snapshot_reports_key_metrics(db, monkeypatch):
    """The snapshot returns counts, oldest pending, stale, top clients, patterns."""
    monkeypatch.setattr(settings, "learning_stale_pending_days", 7)
    monkeypatch.setattr(settings, "learning_per_client_window_seconds", 3600)

    _make_suggestion(db, status="pending", client_id=1)
    _make_suggestion(
        db,
        status="pending",
        client_id=1,
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    _make_suggestion(db, status="approved", client_id=1)
    _make_suggestion(db, status="rejected", client_id=2)

    pattern = LearnedPattern(
        pattern_type="keyword",
        pattern_value="certificado energetico",
        target_class="certificado",
        target_action="classify_as",
        confidence=0.9,
        status="active",
        applied_count=42,
    )
    db.add(pattern)
    db.commit()

    snap = learning_health.health_snapshot(db)

    assert snap["suggestion_counts"]["pending"] == 2
    assert snap["suggestion_counts"]["approved"] == 1
    assert snap["suggestion_counts"]["rejected"] == 1
    assert snap["oldest_pending_age_seconds"] is not None
    assert snap["stale_pending_count"] == 1
    # Only the fresh row for client 1 is in the 1-hour circuit-breaker window.
    # The 30-day-old pending row is past the window.
    assert snap["top_clients_by_pending"][0]["client_id"] == 1
    assert snap["top_clients_by_pending"][0]["pending"] == 1
    assert snap["learned_patterns"]["counts"]["active"] == 1
    assert snap["learned_patterns"]["top_active"][0]["applied_count"] == 42


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _count_stmt(status: str):
    from sqlalchemy import func, select

    return select(func.count(ClassificationSuggestion.id)).where(
        ClassificationSuggestion.status == status
    )


def _all_suggestions():
    from sqlalchemy import select

    return select(ClassificationSuggestion)
