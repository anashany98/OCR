"""add stale_at and integration_client circuit-breaker indexes to classification_suggestions

Revision ID: 0016_learning_loop_health
Revises: 0015_webhook_outbox
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_learning_loop_health"
down_revision = "0015_webhook_outbox"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def upgrade() -> None:
    # stale_at: when the suggestion was first considered stale. NULL means
    # "not yet stale" (still fresh or already finalised).
    op.add_column(
        "classification_suggestions",
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
    )
    if not _index_exists("classification_suggestions", "ix_cs_pending_stale"):
        op.create_index(
            "ix_cs_pending_stale",
            "classification_suggestions",
            ["stale_at"],
            postgresql_where=sa.text("status = 'pending' AND stale_at IS NOT NULL"),
        )

    # Composite index used by the health endpoint: counts of pending suggestions
    # grouped by integration_client, filtered to recent window.
    if not _index_exists("classification_suggestions", "ix_cs_client_status_created"):
        op.create_index(
            "ix_cs_client_status_created",
            "classification_suggestions",
            ["integration_client_id", "status", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_cs_client_status_created", table_name="classification_suggestions")
    op.drop_index("ix_cs_pending_stale", table_name="classification_suggestions")
    op.drop_column("classification_suggestions", "stale_at")
