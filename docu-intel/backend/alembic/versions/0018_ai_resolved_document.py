"""add resolved_document_json to ai_answers

Revision ID: 0018_ai_resolved_document
Revises: 0017_ocr_engine_tracking
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_ai_resolved_document"
down_revision = "0017_ocr_engine_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSON snapshot of the document the agent resolved for this answer
    # (entities + related documents). Nullable: only filled when the user
    # mentions a specific file in their question.
    op.add_column(
        "ai_answers",
        sa.Column("resolved_document_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_answers", "resolved_document_json")
