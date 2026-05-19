"""backlog sprint hardening

Revision ID: 0011_backlog_sprint_hardening
Revises: 0010_professional_workflows
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_backlog_sprint_hardening"
down_revision = "0010_professional_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("page_status", sa.String(length=40), nullable=False, server_default="processed"))
    op.add_column("document_pages", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("document_pages", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("document_pages", sa.Column("processing_time_ms", sa.Integer(), nullable=True))
    op.create_index("ix_document_pages_page_status", "document_pages", ["page_status"])
    op.alter_column("document_pages", "page_status", server_default=None)
    op.alter_column("document_pages", "attempts", server_default=None)

    op.add_column("document_chunks", sa.Column("embedding_provider_used", sa.String(length=80), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_fallback", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("document_chunks", sa.Column("needs_reembedding", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_document_chunks_needs_reembedding", "document_chunks", ["needs_reembedding"])
    op.alter_column("document_chunks", "embedding_fallback", server_default=None)
    op.alter_column("document_chunks", "needs_reembedding", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_document_chunks_needs_reembedding", table_name="document_chunks")
    op.drop_column("document_chunks", "needs_reembedding")
    op.drop_column("document_chunks", "embedding_fallback")
    op.drop_column("document_chunks", "embedding_provider_used")

    op.drop_index("ix_document_pages_page_status", table_name="document_pages")
    op.drop_column("document_pages", "processing_time_ms")
    op.drop_column("document_pages", "error_message")
    op.drop_column("document_pages", "attempts")
    op.drop_column("document_pages", "page_status")
