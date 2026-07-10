"""0046 — Migrate financial Float columns to Numeric(18,2).

Float (IEEE 754 binary64) has rounding errors for decimal fractions
(0.1 + 0.2 != 0.3). Financial columns must use Numeric for exact
arithmetic. This migration alters all money/amount columns from
Float to Numeric(18,2) with a ROUND_HALF_UP policy.

Revision ID: 0046_migrate_financial_to_numeric
Revises: 0045_align_block_type_constraint
Create Date: 2026-07-10
"""
from decimal import ROUND_HALF_UP, Decimal

from alembic import op
import sqlalchemy as sa

revision = "0046_migrate_financial_to_numeric"
down_revision = "0045_align_block_type_constraint"
branch_labels = None
depends_on = None

# (table, column) pairs to migrate from Float to Numeric(18,2).
_FINANCIAL_COLUMNS: list[tuple[str, str]] = [
    ("budgets", "total_amount"),
    ("budget_lines", "unit_price"),
    ("budget_lines", "total_price"),
    ("orders", "total_amount"),
    ("order_lines", "unit_price"),
    ("order_lines", "total_price"),
    ("invoices", "total_amount"),
    ("invoices", "taxable_base"),
    ("invoices", "vat_amount"),
    ("reconciliation_issues", "expected_amount"),
    ("reconciliation_issues", "actual_amount"),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    for table, column in _FINANCIAL_COLUMNS:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column not in cols:
            continue
        # Backfill: round existing Float values to 2 decimal places.
        op.execute(
            f"UPDATE {table} SET {column} = ROUND({column}::numeric, 2) "
            f"WHERE {column} IS NOT NULL"
        )
        op.alter_column(
            table, column,
            existing_type=sa.Float(),
            type_=sa.Numeric(18, 2),
            existing_nullable=True,
        )


def downgrade() -> None:
    for table, column in _FINANCIAL_COLUMNS:
        op.alter_column(
            table, column,
            existing_type=sa.Numeric(18, 2),
            type_=sa.Float(),
            existing_nullable=True,
        )
