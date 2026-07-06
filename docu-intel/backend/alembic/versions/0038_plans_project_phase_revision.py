"""FIX-1: Add project_phase and revision columns to plans table.

The Plan model (app/models/business.py:128-129) defines ``project_phase``
and ``revision`` for multi-sheet plan association (P5), but the database
table was never migrated to include them. This causes every plan
classification to fail with:

    UndefinedColumn: column "project_phase" of relation "plans" does not exist

Revision ID: 0038_plans_project_phase_revision
Revises: 0037_search_performance_indexes
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa

revision = "0038_plans_project_phase_revision"
down_revision = "0037_search_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("project_phase", sa.String(80), nullable=True))
    op.create_index("ix_plans_project_phase", "plans", ["project_phase"])
    op.add_column("plans", sa.Column("revision", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_plans_project_phase", table_name="plans")
    op.drop_column("plans", "revision")
    op.drop_column("plans", "project_phase")
