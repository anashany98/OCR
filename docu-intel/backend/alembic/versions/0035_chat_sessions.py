"""CTX-2 — Alembic migration: chat_sessions + chat_messages.

Adds the persistence layer for per-user chat session state. The state
column is a JSON blob so future "remember this" keys do not need a new
migration; the only schema fields are ownership and timestamps.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0035_chat_sessions"
down_revision = "0034_invoice_deterministic_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("session_uuid", sa.String(length=64), nullable=False),
        sa.Column(
            "state_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_chat_sessions_session_uuid",
        "chat_sessions",
        ["session_uuid"],
        unique=False,
    )
    op.create_index(
        "ix_chat_sessions_last_seen_at",
        "chat_sessions",
        ["last_seen_at"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_chat_sessions_user_uuid",
        "chat_sessions",
        ["user_id", "session_uuid"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("ai_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default="user"
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column(
            "was_structured_hit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_chat_messages_session_id", "chat_messages", ["session_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_chat_messages_session_question",
        "chat_messages",
        ["session_id", "question_id"],
    )


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
