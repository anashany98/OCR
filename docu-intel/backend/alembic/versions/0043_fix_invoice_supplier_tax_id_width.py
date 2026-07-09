"""ensure invoices.supplier_tax_id is varchar(50)

Revision ID: 0043_fix_invoice_supplier_tax_id_width
Revises: 0042_document_level_embedding
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0043_fix_invoice_supplier_tax_id_width"
down_revision = "0042_document_level_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "invoices", "supplier_tax_id",
        existing_type=sa.String(32), type_=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "invoices", "supplier_tax_id",
        existing_type=sa.String(50), type_=sa.String(32),
        existing_nullable=True,
    )
