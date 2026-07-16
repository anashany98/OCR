"""0050 — Invoice line items (Phase 6).

Creates invoice_lines table for persisting extracted line items
from invoices, budgets, and orders.

Revision ID: 0050_invoice_lines
Revises: 0049_project_hierarchy
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0050_invoice_lines"
down_revision = "0049_project_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("reference", sa.String(200)),
        sa.Column("description", sa.Text),
        sa.Column("quantity", sa.Float),
        sa.Column("unit", sa.String(20)),
        sa.Column("unit_price", sa.Numeric(18, 4)),
        sa.Column("total_price", sa.Numeric(18, 2)),
        sa.Column("currency", sa.String(12)),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("invoice_lines")
