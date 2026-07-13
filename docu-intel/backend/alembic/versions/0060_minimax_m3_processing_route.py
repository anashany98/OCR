"""MiniMax M3 (FASE 3) — processing_route column on Document.

The column records the route Hyper-Extract took (text LLM vs
VLM) on the last run so an operator can see the split between
text and vision enrichment in the admin panel.

Revision ID: 0060_minimax_m3_processing_route
Revises: 0059_minimax_m3_extraction_fingerprint_row
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0060_minimax_m3_processing_route"
down_revision = "0059_minimax_m3_extraction_fingerprint_row"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("processing_route", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_documents_processing_route",
        "documents",
        ["processing_route"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_processing_route", table_name="documents")
    op.drop_column("documents", "processing_route")
