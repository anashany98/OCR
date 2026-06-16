"""A4 (Sprint 4): deterministic extraction columns for invoices.

Adds ``supplier_tax_id`` (indexed), ``taxable_base`` and ``vat_amount``
to the ``invoices`` table. The values are already produced by
:func:`app.services.business_extraction.extract_invoice` from the OCR
text via regex; persisting them as columns means:

* "sum of invoices in May" / "invoices for supplier X" can be answered
  by a single indexed SQL query instead of going through the LLM.
* ``supplier_tax_id`` is indexed because "invoices for supplier X" is
  a frequent admin lookup.
* The extraction is deterministic and pre-validated, so the
  aggregation response is grounded in real data, not in an LLM guess.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0034_invoice_deterministic_fields"
down_revision = "0033_partition_audit_and_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoices") as batch:
        batch.add_column(
            sa.Column("supplier_tax_id", sa.String(length=32), nullable=True)
        )
        batch.add_column(sa.Column("taxable_base", sa.Float(), nullable=True))
        batch.add_column(sa.Column("vat_amount", sa.Float(), nullable=True))
        batch.create_index(
            "ix_invoices_supplier_tax_id",
            ["supplier_tax_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("invoices") as batch:
        batch.drop_index("ix_invoices_supplier_tax_id")
        batch.drop_column("vat_amount")
        batch.drop_column("taxable_base")
        batch.drop_column("supplier_tax_id")
