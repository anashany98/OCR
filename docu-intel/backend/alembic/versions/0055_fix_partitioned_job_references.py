"""Remove stale foreign keys left by extraction-job partitioning.

Revision ID: 0055_fix_partitioned_job_references
Revises: 0054_ocr_attempt_traceability
"""

from alembic import op


revision = "0055_fix_partitioned_job_references"
down_revision = "0054_ocr_attempt_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep ingestion metadata writable after ``extraction_jobs`` partitioning.

    PostgreSQL retargets inbound foreign keys when ``extraction_jobs`` is
    renamed to ``extraction_jobs_legacy`` in revision 0033.  The new
    partitioned table cannot expose a unique ``id``-only key, so these two
    integer references must remain application-level links instead of stale
    database foreign keys.  Leaving them in place rejects every new batch
    upload as soon as it creates an extraction job.
    """
    op.execute("ALTER TABLE watched_files DROP CONSTRAINT IF EXISTS watched_files_job_id_fkey")
    op.execute("ALTER TABLE ingestion_events DROP CONSTRAINT IF EXISTS ingestion_events_job_id_fkey")


def downgrade() -> None:
    """No-op: 0054 still uses the partitioned jobs table.

    Re-adding an id-only foreign key here would recreate the invalid legacy
    reference and make ingestion fail again.
    """

