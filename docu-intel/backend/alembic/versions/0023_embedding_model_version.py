"""add DocumentChunk.embedding_model_version (E4 versioned embeddings)

Revision ID: 0023_embedding_model_version
Revises: 0022_ai_answer_feedback
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_embedding_model_version"
down_revision = "0022_ai_answer_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # E4 — track which model version produced each chunk's
    # embedding so the periodic re-embed sweep can find chunks
    # that need updating when the operator changes
    # ``EMBEDDING_MODEL`` in the environment.
    op.add_column(
        "document_chunks",
        sa.Column(
            "embedding_model_version",
            sa.String(length=120),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_chunks_embedding_model_version",
        "document_chunks",
        ["embedding_model_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_embedding_model_version",
        table_name="document_chunks",
    )
    op.drop_column("document_chunks", "embedding_model_version")
