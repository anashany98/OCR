"""Health monitoring and maintenance for the learning loop.

The system has an inherent risk of accumulating "zombie" suggestions if admins
don't review the queue: a noisy or broken external AI client can pile up
hundreds of pending proposals that nobody ever approves or rejects. This
module provides:

* ``mark_stale_suggestions`` — flip ``stale_at`` on rows older than the configured threshold
* ``auto_reject_stale_suggestions`` — move stale rows to ``status='rejected'`` with a synthetic reviewer
* ``client_recent_pending_count`` — count a client's recent pending proposals (circuit-breaker input)
* ``health_snapshot`` — aggregate metrics for the admin dashboard

The circuit breaker itself is *not enforced* here; we surface the metric and
let the admin endpoint / future per-client lockout decide. Hard enforcement
would risk blocking legitimate clients during an integration rollout.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ClassificationSuggestion, LearnedPattern

logger = logging.getLogger(__name__)


def _as_naive_utc(dt: datetime) -> datetime:
    """Strip tzinfo to make a datetime comparable with naive DB columns.

    SQLite (used in tests) doesn't preserve timezone info on DateTime columns.
    Postgres does, so we add the offset for tz-aware columns when needed.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def mark_stale_suggestions(db: Session) -> int:
    """Set ``stale_at`` on all pending rows older than the configured threshold.

    Returns the number of rows touched this tick. Idempotent: rows that already
    have a non-null ``stale_at`` are not modified.
    """
    if settings.learning_stale_pending_days <= 0:
        return 0
    cutoff_aware = datetime.now(timezone.utc) - timedelta(days=settings.learning_stale_pending_days)
    cutoff_naive = _as_naive_utc(cutoff_aware)
    stmt = (
        update(ClassificationSuggestion)
        .where(ClassificationSuggestion.status == "pending")
        .where(ClassificationSuggestion.stale_at.is_(None))
        .where(ClassificationSuggestion.created_at < cutoff_naive)
        .values(stale_at=cutoff_naive)
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def auto_reject_stale_suggestions(db: Session) -> dict[str, int]:
    """Move stale pending rows to ``status='rejected'`` with an audit reason.

    Returns counts so the Celery task can report progress. The action is
    recorded via ``reason`` (overwriting the agent's reason with a short
    note) and via the ``applied_at`` field as a "decision time" proxy.
    """
    if settings.learning_stale_pending_days <= 0:
        return {"rejected": 0, "remaining": 0}

    now_naive = _as_naive_utc(datetime.now(timezone.utc))
    # Re-mark fresh stale (in case the threshold was shortened since the last run)
    mark_stale_suggestions(db)

    pending = list(
        db.scalars(
            select(ClassificationSuggestion)
            .where(ClassificationSuggestion.status == "pending")
            .where(ClassificationSuggestion.stale_at.is_not(None))
            .order_by(ClassificationSuggestion.stale_at.asc())
            .limit(500)
        ).all()
    )
    rejected = 0
    for row in pending:
        row.status = "rejected"
        row.reviewed_at = now_naive
        row.reviewed_by_user_id = None
        if not row.reason or "stale" not in row.reason.lower():
            row.reason = f"{row.reason}\n[auto-rejected after {settings.learning_stale_pending_days}d pending]"
        rejected += 1
    db.commit()

    remaining = db.scalar(
        select(func.count(ClassificationSuggestion.id)).where(
            ClassificationSuggestion.status == "pending"
        )
    )
    return {"rejected": rejected, "remaining": int(remaining or 0)}


def client_recent_pending_count(db: Session, client_id: int) -> int:
    """How many pending suggestions a given client has created in the last window.

    Used as the input to the soft circuit breaker. Returns 0 if no client or
    if the limit is disabled.
    """
    if settings.learning_per_client_max_pending <= 0:
        return 0
    window_start_naive = _as_naive_utc(
        datetime.now(timezone.utc) - timedelta(seconds=settings.learning_per_client_window_seconds)
    )
    return int(
        db.scalar(
            select(func.count(ClassificationSuggestion.id))
            .where(ClassificationSuggestion.integration_client_id == client_id)
            .where(ClassificationSuggestion.status == "pending")
            .where(ClassificationSuggestion.created_at >= window_start_naive)
        )
        or 0
    )


def health_snapshot(db: Session) -> dict[str, Any]:
    """Aggregate health metrics for the admin dashboard.

    Opportunistically marks newly-stale rows so the dashboard always reflects
    the current threshold, even if the daily worker hasn't run yet.
    """
    mark_stale_suggestions(db)

    # Status counts
    status_rows = db.execute(
        select(ClassificationSuggestion.status, func.count(ClassificationSuggestion.id)).group_by(
            ClassificationSuggestion.status
        )
    ).all()
    counts = {"pending": 0, "approved": 0, "rejected": 0, "applied": 0}
    for status_name, count in status_rows:
        counts[status_name] = int(count)

    # Oldest pending
    oldest = db.scalar(
        select(ClassificationSuggestion.created_at)
        .where(ClassificationSuggestion.status == "pending")
        .order_by(ClassificationSuggestion.created_at.asc())
        .limit(1)
    )
    oldest_pending_age_seconds: float | None = None
    if oldest is not None:
        # SQLite strips tzinfo; assume UTC for storage if naive.
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        oldest_pending_age_seconds = (datetime.now(timezone.utc) - oldest).total_seconds()

    # Stale count
    stale_count = int(
        db.scalar(
            select(func.count(ClassificationSuggestion.id))
            .where(ClassificationSuggestion.status == "pending")
            .where(ClassificationSuggestion.stale_at.is_not(None))
        )
        or 0
    )

    # Top clients by pending volume in the last window
    window_start_naive = _as_naive_utc(
        datetime.now(timezone.utc) - timedelta(seconds=settings.learning_per_client_window_seconds)
    )
    client_rows = db.execute(
        select(
            ClassificationSuggestion.integration_client_id,
            func.count(ClassificationSuggestion.id),
        )
        .where(ClassificationSuggestion.status == "pending")
        .where(ClassificationSuggestion.created_at >= window_start_naive)
        .group_by(ClassificationSuggestion.integration_client_id)
        .order_by(func.count(ClassificationSuggestion.id).desc())
        .limit(10)
    ).all()
    top_clients = [
        {"client_id": int(client_id) if client_id is not None else None, "pending": int(count)}
        for client_id, count in client_rows
    ]

    # Learned pattern stats
    pattern_rows = db.execute(
        select(LearnedPattern.status, func.count(LearnedPattern.id)).group_by(LearnedPattern.status)
    ).all()
    pattern_counts = {"active": 0, "disabled": 0, "pending": 0}
    for status_name, count in pattern_rows:
        pattern_counts[status_name] = int(count)

    # Top patterns by applied_count
    top_patterns = list(
        db.scalars(
            select(LearnedPattern)
            .where(LearnedPattern.status == "active")
            .order_by(LearnedPattern.applied_count.desc(), LearnedPattern.updated_at.desc())
            .limit(5)
        ).all()
    )

    return {
        "suggestion_counts": counts,
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "stale_pending_count": stale_count,
        "top_clients_by_pending": top_clients,
        "circuit_breaker": {
            "max_per_client": settings.learning_per_client_max_pending,
            "window_seconds": settings.learning_per_client_window_seconds,
        },
        "learned_patterns": {
            "counts": pattern_counts,
            "top_active": [
                {
                    "id": p.id,
                    "pattern_value": p.pattern_value,
                    "target_class": p.target_class,
                    "applied_count": p.applied_count,
                }
                for p in top_patterns
            ],
        },
        "stale_policy": {
            "threshold_days": settings.learning_stale_pending_days,
        },
    }
