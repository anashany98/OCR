"""add documents.embedding + HNSW index (document-level retrieval)

Revision ID: 0042_document_level_embedding
Revises: 0041_delivery_notes
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0042_document_level_embedding"
down_revision = "0041_delivery_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("embedding", Vector(768), nullable=True))
    op.add_column(
        "documents",
        sa.Column("embedding_model_version", sa.String(120), nullable=True),
    )
    op.create_index(
        "ix_documents_embedding_model_version",
        "documents",
        ["embedding_model_version"],
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_embedding_hnsw "
        "ON documents USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_embedding_hnsw")
    op.drop_index("ix_documents_embedding_model_version", table_name="documents")
    op.drop_column("documents", "embedding_model_version")
    op.drop_column("documents", "embedding")
