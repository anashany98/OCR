"""MiniMax M3 (FASE 5) — versioned prompt on AIAnswer.

Revision ID: 0057_minimax_m3_prompt_version
Revises: 0056_minimax_m3_classification_fingerprint
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0057_minimax_m3_prompt_version"
down_revision = "0056_minimax_m3_classification_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_answers",
        sa.Column("prompt_version", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_answers", "prompt_version")
