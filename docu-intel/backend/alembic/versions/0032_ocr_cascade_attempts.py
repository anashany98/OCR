"""ocr cascade attempts log

Revision ID: 0032_ocr_cascade_attempts
Revises: 0031_pg_trgm_text_search_indexes
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0032_ocr_cascade_attempts"
down_revision = "0031_pg_trgm_text_search_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_cascade_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=40), nullable=False),
        sa.Column("tier_index", sa.Integer(), nullable=False),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["document_pages.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_ocr_cascade_attempts_document_id",
        "ocr_cascade_attempts",
        ["document_id"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_page_id",
        "ocr_cascade_attempts",
        ["page_id"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_page_number",
        "ocr_cascade_attempts",
        ["page_number"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_tier",
        "ocr_cascade_attempts",
        ["tier"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_success",
        "ocr_cascade_attempts",
        ["success"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_created_at",
        "ocr_cascade_attempts",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ocr_cascade_attempts_created_at", table_name="ocr_cascade_attempts"
    )
    op.drop_index(
        "ix_ocr_cascade_attempts_success", table_name="ocr_cascade_attempts"
    )
    op.drop_index("ix_ocr_cascade_attempts_tier", table_name="ocr_cascade_attempts")
    op.drop_index(
        "ix_ocr_cascade_attempts_page_number", table_name="ocr_cascade_attempts"
    )
    op.drop_index(
        "ix_ocr_cascade_attempts_page_id", table_name="ocr_cascade_attempts"
    )
    op.drop_index(
        "ix_ocr_cascade_attempts_document_id", table_name="ocr_cascade_attempts"
    )
    op.drop_table("ocr_cascade_attempts")
