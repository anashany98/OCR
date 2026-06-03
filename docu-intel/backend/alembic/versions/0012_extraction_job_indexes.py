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


def _index_exists(table_name: str, index_name: str, columns: list[str]) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    expected_columns = tuple(columns)
    return any(
        index["name"] == index_name or tuple(index.get("column_names") or ()) == expected_columns
        for index in indexes
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name, columns):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    if any(index["name"] == index_name for index in indexes):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _create_index_if_missing("ix_extraction_jobs_status", "extraction_jobs", ["status"])
    _create_index_if_missing("ix_extraction_jobs_finished_at", "extraction_jobs", ["finished_at"])
    _create_index_if_missing("ix_extraction_jobs_document_id_status", "extraction_jobs", ["document_id", "status"])


def downgrade() -> None:
    _drop_index_if_exists("ix_extraction_jobs_document_id_status", "extraction_jobs")
    _drop_index_if_exists("ix_extraction_jobs_finished_at", "extraction_jobs")
