"""0037 — Search performance indexes.

Adds GIN trigram indexes on document_pages.text and
documents.original_filename for faster ILIKE searches.
Also creates a materialized view for active documents that
the document list endpoint can query instead of filtering
the full table each time.

These indexes are non-destructive and safe to apply on any
installation. The materialized view is refreshed by a periodic
Celery beat task (see maintenance_tasks.py).
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0037_search_performance_indexes"
down_revision = "0036_document_hyperextract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN trigram index on page text for fast ILIKE '%query%'
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_pages_text_trgm "
        "ON document_pages USING gin (text gin_trgm_ops)"
    )
    # GIN trigram index on filename for fast ILIKE '%query%'
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_filename_trgm "
        "ON documents USING gin (original_filename gin_trgm_ops)"
    )
    # Composite index for common filter patterns
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_status_type_created "
        "ON documents (status, document_type, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    # Materialized view for active documents (avoids filtering deleted
    # and failed docs on every list query).
    op.execute(
        "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_active_documents AS "
        "SELECT d.id, d.original_filename, d.document_type, d.status, "
        "d.created_at, d.source_path, d.file_size, d.page_count "
        "FROM documents d "
        "WHERE d.deleted_at IS NULL "
        "AND d.status NOT IN ('failed', 'duplicate') "
        "WITH DATA"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS mv_active_documents_id "
        "ON mv_active_documents (id)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_active_documents")
    op.execute("DROP INDEX IF EXISTS idx_documents_status_type_created")
    op.execute("DROP INDEX IF EXISTS idx_documents_filename_trgm")
    op.execute("DROP INDEX IF EXISTS idx_document_pages_text_trgm")
