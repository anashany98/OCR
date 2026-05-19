"""add extraction job performance indexes

Revision ID: 0012_extraction_job_indexes
Revises: 0011_backlog_sprint_hardening
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_extraction_job_indexes"
down_revision = "0011_backlog_sprint_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_extraction_jobs_status", "extraction_jobs", ["status"])
    op.create_index("ix_extraction_jobs_finished_at", "extraction_jobs", ["finished_at"])
    op.create_index("ix_extraction_jobs_document_id_status", "extraction_jobs", ["document_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_extraction_jobs_document_id_status", table_name="extraction_jobs")
    op.drop_index("ix_extraction_jobs_finished_at", table_name="extraction_jobs")
    op.drop_index("ix_extraction_jobs_status", table_name="extraction_jobs")