"""drop unused mv_active_documents materialized view

Revision ID: 0044_drop_mv_active_documents
Revises: 0043_fix_invoice_supplier_tax_id_width
Create Date: 2026-07-09
"""
from alembic import op

revision = "0044_drop_mv_active_documents"
down_revision = "0043_fix_invoice_supplier_tax_id_width"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_active_documents")


def downgrade() -> None:
    # Recreate with the original explicit column list from 0037,
    # NOT SELECT * — column set may differ after downgrades.
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
