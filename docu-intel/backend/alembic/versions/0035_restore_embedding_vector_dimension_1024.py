"""Restore embedding vector dimension to 1024.

The application settings and current multilingual embedding models
(``bge-m3`` / Granite multilingual) expect 1024-dimensional vectors.
Revision ``0032_fix_embedding_vector_dimension`` changed
``document_chunks.embedding`` to ``vector(768)`` for an older deployed
model, leaving fresh 1024-dimensional embeddings unable to persist.

Changing pgvector dimensions with existing non-null vectors is unsafe, so
the migration clears stored embeddings and marks affected chunks/documents
for explicit re-embedding. That keeps A5's "fail fast, no silent coercion"
policy intact.
"""

from __future__ import annotations

from alembic import op


revision = "0035_restore_embedding_vector_dimension_1024"
down_revision = "0032_fix_embedding_vector_dimension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE documents
        SET needs_reembedding = TRUE
        WHERE id IN (
            SELECT DISTINCT document_id
            FROM document_chunks
            WHERE embedding IS NOT NULL
        )
        """
    )
    op.execute(
        """
        UPDATE document_chunks
        SET embedding = NULL,
            needs_reembedding = TRUE,
            embedding_model_version = NULL
        WHERE embedding IS NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE documents
        SET needs_reembedding = TRUE
        WHERE id IN (
            SELECT DISTINCT document_id
            FROM document_chunks
            WHERE embedding IS NOT NULL
        )
        """
    )
    op.execute(
        """
        UPDATE document_chunks
        SET embedding = NULL,
            needs_reembedding = TRUE,
            embedding_model_version = NULL
        WHERE embedding IS NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768)")
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )
