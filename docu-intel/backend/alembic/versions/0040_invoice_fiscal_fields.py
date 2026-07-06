"""Add fiscal fields to invoices table.

Adds ``supplier_tax_id``, ``taxable_base``, ``vat_amount`` and
``related_order_number`` columns to the ``invoices`` table.  These fields
were already extracted by the business extraction pipeline but never
persisted because the model lacked the corresponding columns.

Revision ID: 0040_invoice_fiscal_fields
Revises: 0039_chunks_tsv_spanish
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0040_invoice_fiscal_fields"
down_revision = "0039_chunks_tsv_spanish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("supplier_tax_id", sa.String(50), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("taxable_base", sa.Float(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("vat_amount", sa.Float(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("related_order_number", sa.String(120), nullable=True),
    )
    op.create_index(
        "ix_invoices_supplier_tax_id",
        "invoices",
        ["supplier_tax_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_supplier_tax_id", table_name="invoices")
    op.drop_column("invoices", "related_order_number")
    op.drop_column("invoices", "vat_amount")
    op.drop_column("invoices", "taxable_base")
    op.drop_column("invoices", "supplier_tax_id")
