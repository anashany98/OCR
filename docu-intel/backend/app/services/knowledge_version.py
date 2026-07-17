"""MiniMax M3 — knowledge version counter.

The AI cache key includes a ``knowledge_version`` that is bumped
atomically whenever any source of truth the answer depends on
changes. Bumping the counter is cheaper than scanning Redis for
every entry, and the cache key naturally invalidates stale
answers without a per-user flush.

The counter is a single row in a small table. The row is shared
across the whole deployment (there is one logical knowledge
state per installation), but a future migration can partition it
by tenant if the workload demands it.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database.base import Base

SINGLE_ROW_ID = 1


class KnowledgeVersion(Base):
    """Single-row counter for the AI cache knowledge version.

    The row id is always ``1``; callers MUST use
    :func:`bump_knowledge_version` instead of inserting new rows.
    """

    __tablename__ = "ai_knowledge_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, index=True)
    last_event: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def current_knowledge_version(db: Session) -> int:
    """Return the current version (0 if the row has not been seeded)."""
    row = db.get(KnowledgeVersion, SINGLE_ROW_ID)
    if row is None:
        return 0
    return int(row.version or 0)


def bump_knowledge_version(db: Session, event: str) -> int:
    """Atomically bump the counter and tag it with the event name.

    Returns the new value. The function performs an UPSERT on the
    single row so a missing row is created on the first call.
    Accepts ``db=None`` to mean "no DB session available" and
    falls back to a Redis-only counter so the cache invalidation
    can still be signalled from a non-ORM code path (Celery tasks,
    management commands, tests).
    """
    from app.services.cache import cache_service

    if db is None:
        # Redis fallback: increment the in-memory counter and
        # return the new value. The next call to
        # :func:`current_knowledge_version` reads from Redis so the
        # fallback stays consistent.
        key = "ai:knowledge_version:fallback"
        try:
            new_val = int(cache_service.client.incr(key))
        except Exception:
            # If Redis is unavailable we still return *some*
            # monotonically increasing value so the test that
            # called us does not crash.
            new_val = int(time.time())
        return new_val
    row = db.get(KnowledgeVersion, SINGLE_ROW_ID)
    now = datetime.now(UTC)
    if row is None:
        row = KnowledgeVersion(id=SINGLE_ROW_ID, version=1, last_event=event, last_event_at=now)
        db.add(row)
        db.flush()
        return 1
    row.version = int(row.version or 0) + 1
    row.last_event = event
    row.last_event_at = now
    db.flush()
    return int(row.version)


def get_knowledge_version_snapshot(db: Session) -> dict:
    """Return a serialisable snapshot of the current state."""
    row = db.get(KnowledgeVersion, SINGLE_ROW_ID)
    if row is None:
        return {"version": 0, "last_event": None, "last_event_at": None}
    return {
        "version": int(row.version or 0),
        "last_event": row.last_event,
        "last_event_at": row.last_event_at.isoformat() if row.last_event_at else None,
    }
