"""add DocumentChunk.chunk_type column (E1 structure-aware chunking)

Revision ID: 0020_document_chunk_type
Revises: 0019_document_needs_reembedding
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0020_document_chunk_type"
down_revision = "0019_document_needs_reembedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # E1 — ``chunk_type`` lets the retriever filter by structural
    # kind (prose vs. table vs. heading) cheaply. The default is
    # ``"text"`` so every existing chunk becomes a prose chunk and
    # the new behaviour is opt-in by content, not by flag. A
    # partial index keeps the index small even when the table
    # holds millions of rows.
    op.add_column(
        "document_chunks",
        sa.Column(
            "chunk_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'text'"),
        ),
    )
    op.create_index(
        "ix_document_chunks_chunk_type",
        "document_chunks",
        ["chunk_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_chunk_type", table_name="document_chunks")
    op.drop_column("document_chunks", "chunk_type")
