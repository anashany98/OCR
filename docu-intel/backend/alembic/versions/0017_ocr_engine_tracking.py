"""add ocr_engine tracking to document_pages

Revision ID: 0017_ocr_engine_tracking
Revises: 0016_learning_loop_health
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_ocr_engine_tracking"
down_revision = "0016_learning_loop_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_pages",
        sa.Column("ocr_engine", sa.String(length=40), nullable=True),
    )
    # Partial index so the admin "pages by engine" view stays cheap.
    op.create_index(
        "ix_document_pages_ocr_engine",
        "document_pages",
        ["ocr_engine"],
        postgresql_where=sa.text("ocr_engine IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_document_pages_ocr_engine", table_name="document_pages")
    op.drop_column("document_pages", "ocr_engine")
