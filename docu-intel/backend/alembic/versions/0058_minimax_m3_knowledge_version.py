"""MiniMax M3 — knowledge version table (single-row counter).

Revision ID: 0058_minimax_m3_knowledge_version
Revises: 0057_minimax_m3_prompt_version
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0058_minimax_m3_knowledge_version"
down_revision = "0057_minimax_m3_prompt_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_knowledge_version",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_event", sa.String(length=80), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ai_knowledge_version_version",
        "ai_knowledge_version",
        ["version"],
        unique=False,
    )
    # Seed the single row so reads return 0 instead of NULL.
    op.execute(
        "INSERT INTO ai_knowledge_version (id, version, last_event) "
        "VALUES (1, 0, 'seed') "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index("ix_ai_knowledge_version_version", table_name="ai_knowledge_version")
    op.drop_table("ai_knowledge_version")
