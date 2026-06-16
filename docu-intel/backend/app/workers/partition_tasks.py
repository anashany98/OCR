"""S3.1 (Sprint 3) — monthly partition maintenance.

The migration ``0033_partition_audit_and_jobs`` seeds the
``audit_logs`` and ``extraction_jobs`` partitions for the current
month plus five future months. Without further action, the
operator would run out of partitions in six months and the next
``INSERT`` would fail with "no partition of relation ... found
for row". This task is the one that keeps the rolling window
topped up.

The task runs on the 25th of every month (see the Celery beat
schedule in ``app.workers.celery_app.celery_app``). On the 25th
we look ahead two months and create the partition for that
month if it does not already exist. The two-month lookahead
covers a reasonable drift between the task running and the
month boundary without requiring a daily run.

The task is a no-op for non-partitioned tables. On a deployment
that runs without the partitioning migration (e.g. SQLite test
DB), the partition-creation query is a no-op.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text

from app.database.session import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger("app.workers.partition_tasks")


# Number of months ahead of the current month to keep a partition
# for. The migration seeds this many months; the task is
# idempotent and adds more when the existing window is about to
# expire.
_LOOKAHEAD_MONTHS = 5


def _month_bounds(reference: datetime, offset_months: int) -> tuple[datetime, datetime]:
    """Return ``(start_of_month, start_of_next_month)`` for the
    month ``offset_months`` after ``reference``. Both
    timestamps are UTC, tz-naive (so they compare against a
    TIMESTAMPTZ column cleanly). The upper bound is exclusive
    per Postgres's ``FOR VALUES FROM ... TO ...`` convention.
    """
    year = reference.year + (reference.month - 1 + offset_months) // 12
    month = (reference.month - 1 + offset_months) % 12 + 1
    start = datetime(year, month, 1, tzinfo=UTC).replace(tzinfo=None)
    next_year = year + (month // 12)
    next_month = (month % 12) + 1
    end = datetime(next_year, next_month, 1, tzinfo=UTC).replace(tzinfo=None)
    return start, end


def _partition_exists(db, parent: str, suffix: str) -> bool:
    """Return True if the ``<parent>_<suffix>`` partition already
    exists. The check uses the SQLAlchemy inspector so the
    task works against any dialect (it just returns False on
    dialects that do not support partitioned tables, e.g.
    SQLite in tests).
    """
    from sqlalchemy import inspect

    inspector = inspect(db.bind)
    return f"{parent}_{suffix}" in set(inspector.get_table_names())


def _create_partition(db, parent: str, *, start: datetime, end: datetime) -> bool:
    """Create one monthly partition on ``parent`` if it does not
    exist. Returns True if a partition was created.
    """
    suffix = f"{start.year:04d}_{start.month:02d}"
    if _partition_exists(db, parent, suffix):
        return False
    partition = f"{parent}_{suffix}"
    db.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {partition} "
            f"PARTITION OF {parent} "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
    )
    logger.info(
        "partition_created parent=%s partition=%s start=%s end=%s",
        parent,
        partition,
        start.isoformat(),
        end.isoformat(),
    )
    return True


@celery_app.task(
    name="app.workers.partition_tasks.ensure_monthly_partitions_task",
)
def ensure_monthly_partitions_task() -> dict:
    """Make sure the next ``_LOOKAHEAD_MONTHS`` months have
    partitions for both ``audit_logs`` and ``extraction_jobs``.

    Designed to run on the 25th of every month (see
    ``celery_app.celery_app.beat_schedule``). The two-month
    lookahead covers a reasonable drift between the task
    running and the month boundary; the rest of the window is
    filled in by a manual operator run if the task ever fails
    for an extended period.

    Returns a summary ``dict`` so the worker log and the
    admin health endpoint can show what was done.
    """
    now = datetime.now(UTC)
    summary = {"audit_logs": 0, "extraction_jobs": 0}
    db = SessionLocal()
    try:
        for offset in range(_LOOKAHEAD_MONTHS + 1):
            start, end = _month_bounds(now, offset)
            for parent in ("audit_logs", "extraction_jobs"):
                if _create_partition(db, parent, start=start, end=end):
                    summary[parent] += 1
        db.commit()
    finally:
        db.close()
    logger.info("ensure_monthly_partitions_summary %s", summary)
    return summary
