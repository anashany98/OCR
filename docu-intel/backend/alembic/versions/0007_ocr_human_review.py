"""ocr human review status

Revision ID: 0007_ocr_human_review
Revises: 0006_budget_scopes
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_ocr_human_review"
down_revision = "0006_budget_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("review_status", sa.String(length=30), nullable=False, server_default="pending"))
    op.add_column("document_pages", sa.Column("review_notes", sa.Text(), nullable=True))
    op.add_column("document_pages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_pages", sa.Column("reviewed_by_id", sa.Integer(), nullable=True))
    op.create_index("ix_document_pages_review_status", "document_pages", ["review_status"])
    op.create_foreign_key(
        "fk_document_pages_reviewed_by_id_users",
        "document_pages",
        "users",
        ["reviewed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("document_pages", "review_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_document_pages_reviewed_by_id_users", "document_pages", type_="foreignkey")
    op.drop_index("ix_document_pages_review_status", table_name="document_pages")
    op.drop_column("document_pages", "reviewed_by_id")
    op.drop_column("document_pages", "reviewed_at")
    op.drop_column("document_pages", "review_notes")
    op.drop_column("document_pages", "review_status")
