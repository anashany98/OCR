"""0048 — Add construction work items tables (PM4.3).

Creates work_chapters, construction_work_items, and
work_item_breakdowns tables for construction measurements
and budget extraction.

Revision ID: 0048_construction_work_items
Revises: 0047_pipeline_stage_tracking
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0048_construction_work_items"
down_revision = "0047_pipeline_stage_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Work chapters — project_id is intentionally without FK because
    # the technical_projects table does not exist yet.  The FK will be
    # added in a future migration once the table is created.
    op.create_table(
        "work_chapters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, index=True),
        sa.Column("code", sa.String(50), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("work_chapters.id", ondelete="SET NULL"), index=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Construction work items — same FK note as above for project_id.
    op.create_table(
        "construction_work_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, index=True),
        sa.Column("chapter_id", sa.Integer, sa.ForeignKey("work_chapters.id", ondelete="SET NULL"), index=True),
        sa.Column("code", sa.String(50), nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Float),
        sa.Column("unit_price", sa.Numeric(18, 4)),
        sa.Column("total_price", sa.Numeric(18, 2)),
        sa.Column("zone", sa.String(200)),
        sa.Column("floor", sa.String(100)),
        sa.Column("room", sa.String(200)),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True),
        sa.Column("page_number", sa.Integer),
        sa.Column("source_method", sa.String(50)),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Work item breakdowns
    op.create_table(
        "work_item_breakdowns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("work_item_id", sa.Integer, sa.ForeignKey("construction_work_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("length_m", sa.Float),
        sa.Column("width_m", sa.Float),
        sa.Column("height_m", sa.Float),
        sa.Column("units", sa.Integer),
        sa.Column("formula", sa.String(500)),
        sa.Column("computed_quantity", sa.Float),
        sa.Column("description", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("work_item_breakdowns")
    op.drop_table("construction_work_items")
    op.drop_table("work_chapters")
