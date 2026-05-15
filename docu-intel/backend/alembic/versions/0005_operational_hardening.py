"""operational hardening and ingestion tracking

Revision ID: 0005_operational_hardening
Revises: 0004_tenant_access
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_operational_hardening"
down_revision = "0004_tenant_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("documents", "file_size", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)

    op.create_table(
        "watched_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("mtime_epoch", sa.Float()),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("extraction_jobs.id", ondelete="SET NULL")),
        sa.Column("error_message", sa.Text()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watched_files_path", "watched_files", ["path"], unique=True)
    op.create_index("ix_watched_files_status", "watched_files", ["status"])
    op.create_index("ix_watched_files_document_id", "watched_files", ["document_id"])
    op.create_index("ix_watched_files_job_id", "watched_files", ["job_id"])

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("source_path", sa.String(length=2048)),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("extraction_jobs.id", ondelete="SET NULL")),
        sa.Column("watched_file_id", sa.Integer(), sa.ForeignKey("watched_files.id", ondelete="SET NULL")),
        sa.Column("details_json", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingestion_events_event_type", "ingestion_events", ["event_type"])
    op.create_index("ix_ingestion_events_source_path", "ingestion_events", ["source_path"])
    op.create_index("ix_ingestion_events_document_id", "ingestion_events", ["document_id"])
    op.create_index("ix_ingestion_events_job_id", "ingestion_events", ["job_id"])
    op.create_index("ix_ingestion_events_watched_file_id", "ingestion_events", ["watched_file_id"])
    op.create_index("ix_ingestion_events_created_at", "ingestion_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_events_created_at", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_watched_file_id", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_job_id", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_document_id", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_source_path", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_event_type", table_name="ingestion_events")
    op.drop_table("ingestion_events")

    op.drop_index("ix_watched_files_job_id", table_name="watched_files")
    op.drop_index("ix_watched_files_document_id", table_name="watched_files")
    op.drop_index("ix_watched_files_status", table_name="watched_files")
    op.drop_index("ix_watched_files_path", table_name="watched_files")
    op.drop_table("watched_files")

    op.alter_column("documents", "file_size", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
