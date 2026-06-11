"""BE-LOOKUP-1 (Sprint 2): normalized doc-number columns for O(1) fuzzy lookup.

Adds ``budget_number_normalized`` to ``budgets`` and
``order_number_normalized`` to ``orders``. These columns store
the result of :func:`app.services.business_extraction._normalize_doc_number`
so that the related-document resolution (``_find_related_budget_id``,
``_find_related_order_id``) can do a single indexed SELECT instead
of loading 500 rows into Python.

The normalization strips whitespace, hyphens, dots, slashes and
lower-cases the number so that ``"2026/143"``, ``"2026-143"``,
``" 2026/143 "`` and ``"2026 143"`` all collapse to ``"2026143"``.

Backfill strategy:
  Postgres: UPDATE budgets SET budget_number_normalized = lower(replace(replace(replace(replace(budget_number, ' ', ''), '-', ''), '.', ''), '/', ''))
  SQLite:   UPDATE budgets SET budget_number_normalized = lower(replace(replace(replace(replace(budget_number, ' ', ''), '-', ''), '.', ''), '/', ''))

Both engines support the ``replace`` chain.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0029_normalized_doc_number_columns"
down_revision = "0028_tenant_default_permissive_group"
branch_labels = None
depends_on = None


_BACKFILL_EXPR = (
    "lower(replace(replace(replace(replace("
    "coalesce(%s, ''), ' ', ''), '-', ''), '.', ''), '/', ''))"
)


def upgrade() -> None:
    # 1. Add the columns.
    with op.batch_alter_table("budgets") as batch:
        batch.add_column(
            sa.Column("budget_number_normalized", sa.String(length=120), nullable=True)
        )
    with op.batch_alter_table("orders") as batch:
        batch.add_column(
            sa.Column("order_number_normalized", sa.String(length=120), nullable=True)
        )

    # 2. Backfill existing rows.
    bind = op.get_bind()
    budget_expr = _BACKFILL_EXPR % "budget_number"
    order_expr = _BACKFILL_EXPR % "order_number"
    op.execute(sa.text(f"UPDATE budgets SET budget_number_normalized = {budget_expr}"))
    op.execute(sa.text(f"UPDATE orders SET order_number_normalized = {order_expr}"))

    # 3. Add indexes.
    op.create_index(
        "ix_budgets_number_normalized",
        "budgets",
        ["budget_number_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_orders_number_normalized",
        "orders",
        ["order_number_normalized"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_number_normalized", table_name="orders")
    op.drop_index("ix_budgets_number_normalized", table_name="budgets")
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("order_number_normalized")
    with op.batch_alter_table("budgets") as batch:
        batch.drop_column("budget_number_normalized")