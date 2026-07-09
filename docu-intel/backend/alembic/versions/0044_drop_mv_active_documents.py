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
    op.execute(
        "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_active_documents AS "
        "SELECT * FROM documents WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS mv_active_documents_id "
        "ON mv_active_documents (id)"
    )
