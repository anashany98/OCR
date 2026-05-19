"""Create valid vector indexes for semantic search."""

from alembic import op


revision = "0008_vector_indexes"
down_revision = "0007_ocr_human_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE embedding IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id_created
        ON document_chunks(document_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_page_number
        ON document_chunks(document_id, page_number);
    """)
    op.execute("ANALYZE document_chunks")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_page_number")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_document_id_created")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
