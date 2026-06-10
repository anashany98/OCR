"""add DocumentPage.ocr_engine_version (re-OCR sweep)

Revision ID: 0025_ocr_engine_version
Revises: 0024_plan_symbols
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_ocr_engine_version"
down_revision = "0024_plan_symbols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tracks the *version* of the OCR engine that produced this page's
    # text (separate from ``ocr_engine`` which only stores the engine
    # name such as ``paddleocr`` / ``pymupdf``). This lets the periodic
    # re-OCR sweep find pages whose engine version is older than the
    # configured ``settings.current_ocr_engine_version`` and re-run them
    # automatically when the operator upgrades the OCR stack.
    op.add_column(
        "document_pages",
        sa.Column(
            "ocr_engine_version",
            sa.String(length=120),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_pages_ocr_engine_version",
        "document_pages",
        ["ocr_engine_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_pages_ocr_engine_version",
        table_name="document_pages",
    )
    op.drop_column("document_pages", "ocr_engine_version")
