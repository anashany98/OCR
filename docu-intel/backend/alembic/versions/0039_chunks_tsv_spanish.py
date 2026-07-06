"""Use Spanish text-search config for BM25 chunks (tsv).

The ``tsv`` generated column on ``document_chunks`` was created with the
``'simple'`` configuration, which does no stemming and treats accented
characters as distinct tokens. For a Spanish corpus this cripples lexical
recall: a query for ``"factura"`` does not match ``"facturas"``, and
``"García"`` does not match ``"Garcia"``.

This migration regenerates the column with the ``'spanish'`` configuration
so the same stemming/normalisation that Postgres applies to the query (via
``plainto_tsquery('spanish', ...)``) is applied at index time. The GIN
index is recreated on top.

A ``'spanish'`` dictionary ships with every Postgres install (pg_catalog),
so no extra extension is needed. We do NOT use ``unaccent`` here on
purpose: numbers, NIFs and codes must match exactly, and ``unaccent``
would normalise away distinctions we want to preserve for those tokens;
stemming alone is enough to recover plural/singular and verb-conjugation
matches.

Reindexing a large chunks table takes a few minutes; the column is
``STORED`` so it is rebuilt synchronously. The index drop/recreate is
ordered to minimise the window without a usable GIN index.

Revision ID: 0039_chunks_tsv_spanish
Revises: 0038_plans_project_phase_revision
Create Date: 2026-07-01
"""

from alembic import op

revision = "0039_chunks_tsv_spanish"
down_revision = "0038_plans_project_phase_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the GIN index built on the old 'simple' tsv before altering
    # the generated column; Postgres refuses to alter a column that a
    # GIN index depends on.
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    # Replace the generated column with the 'spanish' config. GENERATED
    # columns cannot be ALTERed in place, so we drop + re-add.
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tsv")
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS "
        "(to_tsvector('spanish'::regconfig, coalesce(chunk_text, ''))) STORED"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_tsv ON document_chunks USING GIN (tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tsv")
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS "
        "(to_tsvector('simple'::regconfig, coalesce(chunk_text, ''))) STORED"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_tsv ON document_chunks USING GIN (tsv)"
    )
