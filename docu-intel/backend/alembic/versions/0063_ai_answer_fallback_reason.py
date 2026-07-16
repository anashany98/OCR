"""Persist the reason for a grounded or safety-gated chat answer.

Revision ID: 0063_ai_answer_fallback_reason
Revises: 0062_cad_structured_extraction
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0063_ai_answer_fallback_reason"
down_revision = "0062_cad_structured_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_answers", sa.Column("fallback_reason", sa.String(length=120), nullable=True))
    op.create_index("ix_ai_answers_fallback_reason", "ai_answers", ["fallback_reason"])


def downgrade() -> None:
    op.drop_index("ix_ai_answers_fallback_reason", table_name="ai_answers")
    op.drop_column("ai_answers", "fallback_reason")
