"""document quality status

Revision ID: 0009_quality_status
Revises: 0008_vector_indexes
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_quality_status"
down_revision = "0008_vector_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("quality_status", sa.String(length=50), nullable=False, server_default="pending"))
    op.add_column("documents", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("quality_flags_json", sa.JSON(), nullable=False, server_default="[]"))
    op.create_index("ix_documents_quality_status", "documents", ["quality_status"])
    op.alter_column("documents", "quality_status", server_default=None)
    op.alter_column("documents", "quality_flags_json", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_documents_quality_status", table_name="documents")
    op.drop_column("documents", "quality_flags_json")
    op.drop_column("documents", "quality_score")
    op.drop_column("documents", "quality_status")
