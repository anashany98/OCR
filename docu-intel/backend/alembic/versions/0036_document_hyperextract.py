"""0036 — Hyper-Extract persistence.

Adds ``document_extractions`` so a Hyper-Extract run leaves a row per
(document, attempt). The table is intentionally append-only and the
payload is stored in JSON columns so future template changes do not
require a new migration.

Hyper-Extract is opt-in (``HYPEREXTRACT_ENABLED=false`` by default),
so an operator that never enables the feature will simply have an
empty table. The migration is non-destructive and safe to apply on
installations that have never run the service.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0036_document_hyperextract"
down_revision = "0035_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "fields_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "entities_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "relations_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "warnings_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("raw_output_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_document_extractions_document_id",
        "document_extractions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extractions_document_type",
        "document_extractions",
        ["document_type"],
        unique=False,
    )
    op.create_index(
        "ix_document_extractions_status",
        "document_extractions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("document_extractions")
