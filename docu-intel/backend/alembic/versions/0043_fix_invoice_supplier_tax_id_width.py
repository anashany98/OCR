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
    # 0040 already created this as varchar(50); this migration is a
    # safety net for deployments where it was created with a shorter
    # type. existing_type matches what 0040 intended.
    op.alter_column(
        "invoices", "supplier_tax_id",
        existing_type=sa.String(50), type_=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    # F1-05: precheck — refuse to truncate if any value exceeds 32 chars.
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT count(*) FROM invoices WHERE length(supplier_tax_id) > 32")
    )
    long_count = result.scalar()
    if long_count and long_count > 0:
        raise ValueError(
            f"Cannot downgrade: {long_count} invoice(s) have supplier_tax_id "
            f"longer than 32 characters. Truncate or delete them first."
        )
    op.alter_column(
        "invoices", "supplier_tax_id",
        existing_type=sa.String(50), type_=sa.String(32),
        existing_nullable=True,
    )
