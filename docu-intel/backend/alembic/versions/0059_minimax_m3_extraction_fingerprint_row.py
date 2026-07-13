"""MiniMax M3 (FASE 3) — extraction fingerprint column on
DocumentExtraction so each row carries the exact fingerprint it
was computed with. Idempotence is now validated against this
column, not against the (frequently stale) document row.

Revision ID: 0059_minimax_m3_extraction_fingerprint_row
Revises: 0058_minimax_m3_knowledge_version
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0059_minimax_m3_extraction_fingerprint_row"
down_revision = "0058_minimax_m3_knowledge_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_extractions",
        sa.Column("extraction_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_document_extractions_extraction_fingerprint",
        "document_extractions",
        ["extraction_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_extractions_extraction_fingerprint",
        table_name="document_extractions",
    )
    op.drop_column("document_extractions", "extraction_fingerprint")
