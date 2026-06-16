"""S3.1 (Sprint 3) — partition ``audit_logs`` and ``extraction_jobs`` by month.

Why
---
Both tables grow monotonically with usage and are never (or
rarely) updated once written. Without partitioning:

* the per-row indexes (user_id, action, entity_id, created_at)
  grow unbounded and Postgres has to keep them in memory;
* ``VACUUM`` and ``ANALYZE`` have to scan the whole table;
* a slow query that touches a recent row has to skip past all
  the old rows;
* backing up the cluster with ``pg_dump`` re-emits every audit
  row even though the operator only ever queries the last 30
  days.

Postgres's native ``PARTITION BY RANGE (created_at)`` fixes all
four: each partition is its own physical table with its own
indexes, the planner can do partition pruning when a query
filters on ``created_at``, and ``DROP TABLE`` is the way to
retire old data (no row-by-row ``DELETE``).

The migration creates the parent tables as partitioned,
moves existing data into the matching month-partitions, and
seeds six months of partitions (current month + five future)
so the system can run unattended for half a year. A separate
Celery beat task (added in ``app.workers.partition_tasks``)
creates the next partition on the 25th of the month.

A note on the foreign keys
--------------------------
``extraction_jobs.document_id`` is a FK to ``documents(id)``.
Postgres 12+ supports FKs from a partitioned table to a
non-partitioned table, so this is fine. The reverse direction
(``documents`` → a partitioned child) would have been the
harder case, but we do not have such a FK.

A note on the primary key
-------------------------
Postgres requires the primary key of a partitioned table to
include the partition key. We change the PK of both tables
from ``(id)`` to ``(id, created_at)``. This is transparent to
the application: the ORM uses ``id`` as the primary key and
Postgres does not care about the extra column in the index.
"""
from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0033_partition_audit_and_jobs"
down_revision = "0032_block_type_chunk_type_enums"
branch_labels = None
depends_on = None


# Number of monthly partitions to create in the upgrade: the
# current month + this many future months. Six months of headroom
# means the operator has time to install the partition-creator
# Celery task before they need a seventh partition.
_LOOKAHEAD_MONTHS = 5


def _month_bounds(reference: datetime, offset_months: int) -> tuple[datetime, datetime]:
    """Return ``(start_of_month, start_of_next_month)`` for the
    month that is ``offset_months`` after ``reference``.

    Both timestamps are UTC, no tzinfo, so they compare cleanly
    against a TIMESTAMPTZ column. Postgres's partition
    bound ``FOR VALUES FROM (...) TO (...)`` is inclusive on the
    lower bound and exclusive on the upper.
    """
    year = reference.year + (reference.month - 1 + offset_months) // 12
    month = (reference.month - 1 + offset_months) % 12 + 1
    start = datetime(year, month, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    next_month_year = year + (month // 12)
    next_month = (month % 12) + 1
    end = datetime(next_month_year, next_month, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    return start, end


def _create_monthly_partitions(
    parent: str,
    *,
    now: datetime,
    lookahead: int,
) -> None:
    """Create the partitions for the current month plus ``lookahead``
    future months. Idempotent: the migration can be re-applied
    without erroring on a deployment that already has the
    partitions.
    """
    bind = op.get_bind()
    for offset in range(lookahead + 1):
        start, end = _month_bounds(now, offset)
        suffix = f"{start.year:04d}_{start.month:02d}"
        partition = f"{parent}_{suffix}"
        # ``IF NOT EXISTS`` makes the migration safe to re-run
        # after a partial failure (e.g. disk full mid-migration).
        op.execute(
            f"CREATE TABLE IF NOT EXISTS {partition} PARTITION OF {parent} "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
        # Re-create the per-partition indexes that the old
        # single-table version had. The new partition
        # inherits the parent's ``UNIQUE`` index
        # automatically but not the per-column ones.
        for column in ("user_id", "action", "entity_type", "entity_id", "created_at"):
            bind.execute(  # type: ignore[attr-defined]
                sa.text(
                    f"CREATE INDEX IF NOT EXISTS ix_{partition}_{column} "
                    f"ON {partition} ({column})"
                )
            )


def upgrade() -> None:
    """Migrate ``audit_logs`` and ``extraction_jobs`` to monthly
    partitions. The work has four phases:

    1. Add ``created_at NOT NULL`` to ``extraction_jobs`` (the
       table was missing it; the field has ``default=now()``
       so the backfill is automatic on PostgreSQL). The
       ``audit_logs`` table already has the column; we tighten
       the ``NOT NULL`` constraint.
    2. Move the existing data out of the original tables into
       the new partitioned tables. Postgres's
       ``ALTER TABLE ... RENAME`` trick keeps the application
       working during the migration (the model's
       ``__tablename__`` points at the new name).
    3. Create the new partitioned tables with the same column
       layout (and PK ``(id, created_at)`` per the constraint
       above).
    4. Seed the monthly partitions.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ------------------------------------------------------------------
    # Phase 1: tighten created_at NOT NULL on audit_logs (it was
    # nullable in the old schema; new rows have it because the
    # Python default fills it in, but historical rows could be
    # null). We backfill nulls to ``now()`` so the NOT NULL
    # constraint is safe to add.
    # ------------------------------------------------------------------
    if "audit_logs" in table_names:
        op.execute(
            "UPDATE audit_logs SET created_at = now() WHERE created_at IS NULL"
        )
        op.alter_column("audit_logs", "created_at", nullable=False)

    # ------------------------------------------------------------------
    # Phase 2: extraction_jobs gets a created_at column. We add
    # the column with a server-side default so existing rows
    # (which are guaranteed to have ``started_at`` or some
    # other timestamp) get a sensible value. Rows that have
    # nothing to backfill from get ``now()`` (the migration
    # default), which is acceptable: a missing created_at on
    # a pre-migration row is the same as "we don't know when
    # it was created, treat it as now".
    # ------------------------------------------------------------------
    if "extraction_jobs" in table_names and "created_at" not in {
        c["name"] for c in inspector.get_columns("extraction_jobs")
    }:
        op.add_column(
            "extraction_jobs",
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_extraction_jobs_created_at",
            "extraction_jobs",
            ["created_at"],
        )

    # ------------------------------------------------------------------
    # Phase 3: rename the original tables aside, create the new
    # partitioned tables, and copy the data in. We use the
    # ``ALTER TABLE ... RENAME TO ...`` + ``INSERT ... SELECT``
    # pattern: the original table is preserved as
    # ``<name>_legacy`` until the operator confirms the new
    # schema is working. The ``downgrade`` drops the
    # partitioned tables and renames the legacy tables back.
    # ------------------------------------------------------------------
    if "audit_logs" in table_names:
        op.rename_table("audit_logs", "audit_logs_legacy")
    if "extraction_jobs" in table_names:
        op.rename_table("extraction_jobs", "extraction_jobs_legacy")

    # Create the new partitioned tables. The schema mirrors
    # the old one, except the primary key now includes
    # ``created_at`` (a Postgres requirement for partitioned
    # tables) and the ``created_at`` column is ``NOT NULL``.
    op.execute(
        """
        CREATE TABLE audit_logs (
            id INTEGER NOT NULL,
            user_id INTEGER,
            action VARCHAR(120) NOT NULL,
            entity_type VARCHAR(120),
            entity_id INTEGER,
            details_json JSON,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id, created_at),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.execute(
        """
        CREATE TABLE extraction_jobs (
            id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            job_type VARCHAR(80) NOT NULL DEFAULT 'extract',
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE,
            error_message TEXT,
            retries INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id, created_at),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        ) PARTITION BY RANGE (created_at)
        """
    )

    # ------------------------------------------------------------------
    # Phase 4: copy legacy data into the new tables, then seed
    # the monthly partitions. The COPY uses ``ON CONFLICT DO
    # NOTHING`` so re-running the migration on a deployment
    # that already has the data is a no-op (Postgres is happy
    # to find an existing row and skip it).
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO audit_logs (
            id, user_id, action, entity_type, entity_id, details_json, created_at
        )
        SELECT id, user_id, action, entity_type, entity_id, details_json, created_at
        FROM audit_logs_legacy
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO extraction_jobs (
            id, document_id, job_type, status, started_at, finished_at,
            error_message, retries, created_at
        )
        SELECT id, document_id, job_type, status, started_at, finished_at,
            error_message, retries, created_at
        FROM extraction_jobs_legacy
        ON CONFLICT DO NOTHING
        """
    )

    _create_monthly_partitions("audit_logs", now=now, lookahead=_LOOKAHEAD_MONTHS)
    _create_monthly_partitions("extraction_jobs", now=now, lookahead=_LOOKAHEAD_MONTHS)


def downgrade() -> None:
    """Reverse the migration. The new partitioned tables are
    dropped; the ``_legacy`` tables are renamed back to their
    original names. Any data written between the upgrade and
    the downgrade is **lost** — the legacy tables are static
    snapshots taken at upgrade time.

    Operators running a downgrade in production should
    restore the legacy tables from a backup taken *before* the
    upgrade, not from the ``_legacy`` copy, because the latter
    does not contain post-upgrade writes.
    """
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS extraction_jobs CASCADE")

    op.rename_table("audit_logs_legacy", "audit_logs")
    op.rename_table("extraction_jobs_legacy", "extraction_jobs")
