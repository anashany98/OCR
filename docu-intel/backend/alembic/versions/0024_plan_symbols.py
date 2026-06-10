"""add PlanSymbol table (P2 YOLO plan symbol detection)

Revision ID: 0024_plan_symbols
Revises: 0023_embedding_model_version
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_plan_symbols"
down_revision = "0023_embedding_model_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # P2 — Plan symbol detection (YOLOv8 with the SamirShabani/Architect
    # pretrained model by default). Each detection is one row, with the
    # symbol class (snake_case), confidence, page number and bounding box
    # in PDF coordinates (points).
    #
    # Why one row per detection and not JSON on Plan:
    # - Filtering "documents with fire_extinguisher on page 3" needs
    #   indexed access on ``symbol_class`` and ``page_number``.
    # - Aggregations (counts per class per plan) need a real table.
    # - The bounding box needs to be queryable for downstream tools
    #   (e.g. count of outlets per room).
    op.create_table(
        "plan_symbols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("symbol_class", sa.String(length=80), nullable=False, index=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=True),
        sa.Column("bbox_y1", sa.Float(), nullable=True),
        sa.Column("bbox_x2", sa.Float(), nullable=True),
        sa.Column("bbox_y2", sa.Float(), nullable=True),
        # ``source_model`` records which detector produced the row
        # (e.g. ``yolov8m_architect``, ``custom_v1``). Useful when the
        # operator swaps the model and wants to know which rows are
        # stale.
        sa.Column("source_model", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_plan_symbols_plan_class",
        "plan_symbols",
        ["plan_id", "symbol_class"],
    )


def downgrade() -> None:
    op.drop_index("ix_plan_symbols_plan_class", table_name="plan_symbols")
    op.drop_table("plan_symbols")
