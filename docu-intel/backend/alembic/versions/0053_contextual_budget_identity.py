"""Contextual budget and deterministic project identity.

Revision ID: 0053_contextual_budget_identity
Revises: 0052_image_analysis
"""

from alembic import op
import sqlalchemy as sa

revision = "0053_contextual_budget_identity"
down_revision = "0052_image_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_scopes", sa.Column("year", sa.Integer(), nullable=True))
    op.add_column("budget_scopes", sa.Column("brand_id", sa.Integer(), nullable=True))
    op.add_column("budget_scopes", sa.Column("hotel_id", sa.Integer(), nullable=True))
    op.add_column("budget_scopes", sa.Column("context_key", sa.String(length=320), nullable=True))
    op.add_column("budget_scopes", sa.Column("legacy_unscoped", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_foreign_key("fk_budget_scopes_brand_id", "budget_scopes", "hotel_chains", ["brand_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_budget_scopes_hotel_id", "budget_scopes", "hotels", ["hotel_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_budget_scopes_context", "budget_scopes", ["year", "brand_id", "hotel_id", "budget_code"])
    op.drop_index("ix_budget_scopes_budget_code", table_name="budget_scopes")
    # PostgreSQL 16 treats NULL hotel IDs as equal here, matching the
    # domain identity for direct-brand budgets.
    op.execute("CREATE UNIQUE INDEX uq_budget_scope_context ON budget_scopes (year, brand_id, hotel_id, budget_code) NULLS NOT DISTINCT WHERE legacy_unscoped = false")
    op.execute("CREATE UNIQUE INDEX uq_project_context_budget ON projects (year, brand_id, hotel_id, primary_budget_scope_id) NULLS NOT DISTINCT WHERE primary_budget_scope_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_project_context_budget")
    op.execute("DROP INDEX IF EXISTS uq_budget_scope_context")
    op.create_index("ix_budget_scopes_budget_code", "budget_scopes", ["budget_code"], unique=True)
    op.drop_index("ix_budget_scopes_context", table_name="budget_scopes")
    op.drop_constraint("fk_budget_scopes_hotel_id", "budget_scopes", type_="foreignkey")
    op.drop_constraint("fk_budget_scopes_brand_id", "budget_scopes", type_="foreignkey")
    op.drop_column("budget_scopes", "legacy_unscoped")
    op.drop_column("budget_scopes", "context_key")
    op.drop_column("budget_scopes", "hotel_id")
    op.drop_column("budget_scopes", "brand_id")
    op.drop_column("budget_scopes", "year")
