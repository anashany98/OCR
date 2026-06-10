"""add AIAnswerFeedback + ai_answer_sources.weight (R3 feedback loop)

Revision ID: 0022_ai_answer_feedback
Revises: 0021_document_chunks_tsv
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_ai_answer_feedback"
down_revision = "0021_document_chunks_tsv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # R3 — feedback loop needs:
    # * a new ``ai_answer_feedback`` table (one row per vote);
    # * a ``weight`` column on ``ai_answer_sources`` so the
    #   retriever can boost / penalise a chunk that the community
    #   endorsed or rejected.

    op.create_table(
        "ai_answer_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "answer_id",
            sa.Integer(),
            sa.ForeignKey("ai_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("vote", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ai_answer_feedback_answer_id",
        "ai_answer_feedback",
        ["answer_id"],
    )
    op.create_index(
        "ix_ai_answer_feedback_user_id",
        "ai_answer_feedback",
        ["user_id"],
    )
    op.create_index(
        "ix_ai_answer_feedback_created_at",
        "ai_answer_feedback",
        ["created_at"],
    )

    op.add_column(
        "ai_answer_sources",
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )
    op.create_index(
        "ix_ai_answer_sources_weight",
        "ai_answer_sources",
        ["weight"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_answer_sources_weight", table_name="ai_answer_sources")
    op.drop_column("ai_answer_sources", "weight")
    op.drop_index("ix_ai_answer_feedback_created_at", table_name="ai_answer_feedback")
    op.drop_index("ix_ai_answer_feedback_user_id", table_name="ai_answer_feedback")
    op.drop_index("ix_ai_answer_feedback_answer_id", table_name="ai_answer_feedback")
    op.drop_table("ai_answer_feedback")
