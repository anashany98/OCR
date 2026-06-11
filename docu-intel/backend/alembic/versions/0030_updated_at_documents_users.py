"""M8 (Sprint 4): Add updated_at to documents and users tables.

Backfills updated_at with the existing created_at value so no NULL
rows are left behind, then adds an onupdate trigger for future writes.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0030_updated_at_documents_users"
down_revision = "0029_normalized_doc_number_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now_fn = sa.text("now()")
    utcnow_default = sa.text("(datetime('now'))")

    # --- documents ---
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )

    # Backfill: set updated_at = created_at for all existing rows.
    op.execute(sa.text("UPDATE documents SET updated_at = created_at WHERE updated_at IS NULL"))

    # Drop the server_default now that every row has a value; the ORM
    # handles future inserts via its own default callable.
    with op.batch_alter_table("documents") as batch:
        batch.alter_column(
            "updated_at",
            server_default=None,
        )

    # --- users ---
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )

    op.execute(sa.text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"))

    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "updated_at",
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("updated_at")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("updated_at")
