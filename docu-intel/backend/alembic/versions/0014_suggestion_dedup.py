"""add unique partial index on classification_suggestions to prevent duplicates

Revision ID: 0014_suggestion_dedup
Revises: 0013_learning_loop
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_suggestion_dedup"
down_revision = "0013_learning_loop"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def upgrade() -> None:
    if not _index_exists("classification_suggestions", "uq_cs_pending_active"):
        op.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX uq_cs_pending_active
                ON classification_suggestions (document_id, suggestion_type, COALESCE(integration_client_id, 0))
                WHERE status IN ('pending', 'approved')
                """
            )
        )


def downgrade() -> None:
    if _index_exists("classification_suggestions", "uq_cs_pending_active"):
        op.drop_index("uq_cs_pending_active", table_name="classification_suggestions")
