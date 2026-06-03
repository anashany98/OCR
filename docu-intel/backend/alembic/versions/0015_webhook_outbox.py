"""add webhook_outbox table for reliable webhook delivery with retry + DLQ

Revision ID: 0015_webhook_outbox
Revises: 0014_suggestion_dedup
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_webhook_outbox"
down_revision = "0014_suggestion_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        # status: pending | sending | delivered | dead_letter
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_response_code", sa.Integer(), nullable=True),
        sa.Column("signature_header", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Index for the worker: pick up pending rows whose next_attempt_at is due,
    # ordered by next_attempt_at so we drain oldest first.
    op.create_index(
        "ix_webhook_outbox_pending_due",
        "webhook_outbox",
        ["status", "next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Index for the admin "dead-letter" view.
    op.create_index(
        "ix_webhook_outbox_dead_letter",
        "webhook_outbox",
        ["status", "dead_lettered_at"],
        postgresql_where=sa.text("status = 'dead_letter'"),
    )

    # Idempotency: a unique partial index on (idempotency_key) where it is set,
    # so we can dedupe replays safely.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_outbox_idempotency
            ON webhook_outbox (idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_webhook_outbox_idempotency"))
    op.drop_index("ix_webhook_outbox_dead_letter", table_name="webhook_outbox")
    op.drop_index("ix_webhook_outbox_pending_due", table_name="webhook_outbox")
    op.drop_table("webhook_outbox")
