"""OCR attempt traceability and calibrated decisions.

Revision ID: 0054_ocr_attempt_traceability
Revises: 0053_contextual_budget_identity
"""

from alembic import op
import sqlalchemy as sa


revision = "0054_ocr_attempt_traceability"
down_revision = "0053_contextual_budget_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("ocr_calibrated_confidence", sa.Float(), nullable=True))
    op.add_column("document_pages", sa.Column("ocr_content_kind", sa.String(length=40), nullable=True))
    op.add_column("document_pages", sa.Column("ocr_decision", sa.String(length=40), nullable=True))
    op.add_column(
        "document_pages",
        sa.Column("ocr_decision_reasons_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.create_index("ix_document_pages_ocr_calibrated_confidence", "document_pages", ["ocr_calibrated_confidence"])
    op.create_index("ix_document_pages_ocr_content_kind", "document_pages", ["ocr_content_kind"])
    op.create_index("ix_document_pages_ocr_decision", "document_pages", ["ocr_decision"])
    op.create_table(
        "ocr_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("document_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(length=80), nullable=False),
        sa.Column("engine_version", sa.String(length=120), nullable=True),
        sa.Column("route", sa.String(length=80), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("raw_confidence", sa.Float(), nullable=True),
        sa.Column("calibrated_confidence", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column("decision_reasons_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_ocr_attempts_page_id", "ocr_attempts", ["page_id"])
    op.create_index("ix_ocr_attempts_selected", "ocr_attempts", ["selected"])


def downgrade() -> None:
    op.drop_index("ix_ocr_attempts_selected", table_name="ocr_attempts")
    op.drop_index("ix_ocr_attempts_page_id", table_name="ocr_attempts")
    op.drop_table("ocr_attempts")
    op.drop_index("ix_document_pages_ocr_decision", table_name="document_pages")
    op.drop_index("ix_document_pages_ocr_content_kind", table_name="document_pages")
    op.drop_index("ix_document_pages_ocr_calibrated_confidence", table_name="document_pages")
    op.drop_column("document_pages", "ocr_decision_reasons_json")
    op.drop_column("document_pages", "ocr_decision")
    op.drop_column("document_pages", "ocr_content_kind")
    op.drop_column("document_pages", "ocr_calibrated_confidence")
