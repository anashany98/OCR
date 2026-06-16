"""Fix embedding vector dimension: vector(1024) -> vector(768).

The DB column ``document_chunks.embedding`` was created as ``vector(1024)``
for BGE-M3, but the deployed model is ``nomic-embed-text:v1.5`` which
outputs 768-dimensional vectors.  All extraction jobs fail with:

    ValueError: expected 1024 dimensions, not 768

This migration alters the column to ``vector(768)`` and rebuilds the
HNSW index accordingly.  Since ``document_chunks`` is currently empty
(all insertions failed), this is a safe, zero-data-loss change.
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
#
# NOTE: this revision was originally branched off
# ``0031_pg_trgm_text_search_indexes`` in parallel with
# ``0032_block_type_chunk_type_enums``. That left Alembic with
# two heads (``0032_block_type_chunk_type_enums`` and this file)
# and the rest of the chain (0033, 0034, ...) only followed
# the enums revision, so this migration was silently orphaned:
# ``alembic upgrade head`` would never run it, and the HNSW
# index plus the ``vector(768)`` column never got applied.
#
# The fix is to re-chain in series at the end of the chain:
# depend on ``0034_invoice_deterministic_fields`` so this
# becomes the single new head. This migration only touches
# ``document_chunks.embedding`` and its HNSW index; none of
# the earlier revisions in the chain (0031–0034) modify that
# column or that index, so the order is safe.
#
# The resulting chain is:
#   0031 → 0032_enums → 0033 → 0034 → 0032_embedding_fix
# (i.e. this revision id sits *after* 0034 even though the
# numeric prefix is 0032; that's fine for Alembic, which orders
# by ``down_revision`` chains, not by file name).
revision = "0032_fix_embedding_vector_dimension"
down_revision = "0034_invoice_deterministic_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the HNSW index first (it depends on the old vector type).
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    # Alter the column type from vector(1024) to vector(768).
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768)")
    # Recreate the HNSW index with the new dimension.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )
