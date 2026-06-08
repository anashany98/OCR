"""add Document.needs_reembedding flag (A7 periodic re-embed)

Revision ID: 0019_document_needs_reembedding
Revises: 0018_ai_resolved_document
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0019_document_needs_reembedding"
down_revision = "0018_ai_resolved_document"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A7 - the periodic re-embed sweeper needs a cheap way to find
    # documents that still need attention without having to LEFT JOIN
    # ``document_chunks`` and aggregate on every tick. The flag is
    # set to ``True`` by the embedding pipeline whenever any chunk
    # for the document lands with ``needs_reembedding=True``; it is
    # cleared by ``reembed_document`` (or by the periodic sweep
    # itself) when the chunks are successfully re-embedded.
    op.add_column(
        "documents",
        sa.Column(
            "needs_reembedding",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_documents_needs_reembedding",
        "documents",
        ["needs_reembedding"],
        postgresql_where=sa.text("needs_reembedding IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_documents_needs_reembedding", table_name="documents")
    op.drop_column("documents", "needs_reembedding")
