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
    # supplier_tax_id/taxable_base/vat_amount los añade 0040 a String(50). No-op.
    pass


def downgrade() -> None:
    # No-op: this migration added nothing (columns are in 0040).
    # Dropping them here would break 0040's downgrade which owns them.
    pass
