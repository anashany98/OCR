"""add document_chunks.tsv + GIN index (E2 BM25)

Revision ID: 0021_document_chunks_tsv
Revises: 0020_document_chunk_type
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_document_chunks_tsv"
down_revision = "0020_document_chunk_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # E2 — real hybrid search uses three signals: cosine similarity
    # on the embedding (semantic), ILIKE on the text (substring
    # match), and BM25 via PostgreSQL's full-text search (proper
    # keyword ranking with term frequency, document frequency and
    # document length normalisation). The first two are already
    # there; this migration adds the third.
    #
    # Strategy: a generated column ``tsv`` derived from
    # ``chunk_text`` via ``to_tsvector('simple', chunk_text)``. We
    # use the 'simple' configuration so accented Spanish, the
    # ASCII-only output of OCR on noisy scans, and English text
    # all tokenise cleanly. A deployment that needs stemming
    # (Spanish/Portuguese) can override the regconfig in a later
    # migration without changing the schema.
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(chunk_text, ''))) STORED"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_tsv ON document_chunks USING GIN (tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tsv")
