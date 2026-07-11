"""0052 — Image analysis model (Phase 5).

Creates image_analyses table for structured visual analysis with
multi-label taxonomy, per-fact confidence, and sensitive data detection.

Revision ID: 0052_image_analysis
Revises: 0051_communication_models
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON
from pgvector.sqlalchemy import Vector

revision = "0052_image_analysis"
down_revision = "0051_communication_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("occurrence_id", sa.Integer, sa.ForeignKey("document_occurrences.id", ondelete="SET NULL"), index=True),
        sa.Column("labels_json", JSON, nullable=False, server_default="[]"),
        sa.Column("description", sa.Text),
        sa.Column("visible_text", sa.Text),
        sa.Column("objects_json", JSON),
        sa.Column("materials_json", JSON),
        sa.Column("colors_json", JSON),
        sa.Column("measurements_json", JSON),
        sa.Column("product_refs_json", JSON),
        sa.Column("room_or_zone", sa.String(300)),
        sa.Column("installation_state", sa.String(100)),
        sa.Column("issue_json", JSON),
        sa.Column("sensitive_data_json", JSON),
        sa.Column("visual_embedding", Vector(768)),
        sa.Column("perceptual_hash", sa.String(64), index=True),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("image_analyses")
