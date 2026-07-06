"""Add delivery_notes and delivery_note_lines tables.

Adds structured extraction support for delivery notes (albaranes).
Previously, albaranes were only OCR'd and indexed as free text.
Now they get persistent fields (supplier, client, date, total) and
line-item extraction (reference, description, quantity, unit, price).

Revision ID: 0041_delivery_notes
Revises: 0040_invoice_fiscal_fields
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0041_delivery_notes"
down_revision = "0040_invoice_fiscal_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delivery_number", sa.String(120), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(12), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_delivery_notes_document_id",
        "delivery_notes",
        ["document_id"],
    )
    op.create_index(
        "ix_delivery_notes_delivery_number",
        "delivery_notes",
        ["delivery_number"],
    )
    op.create_index(
        "ix_delivery_notes_supplier_name",
        "delivery_notes",
        ["supplier_name"],
    )

    op.create_table(
        "delivery_note_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "delivery_note_id",
            sa.Integer(),
            sa.ForeignKey("delivery_notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("total_price", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_delivery_note_lines_delivery_note_id",
        "delivery_note_lines",
        ["delivery_note_id"],
    )
    op.create_index(
        "ix_delivery_note_lines_reference",
        "delivery_note_lines",
        ["reference"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_note_lines_reference", table_name="delivery_note_lines")
    op.drop_index("ix_delivery_note_lines_delivery_note_id", table_name="delivery_note_lines")
    op.drop_table("delivery_note_lines")
    op.drop_index("ix_delivery_notes_supplier_name", table_name="delivery_notes")
    op.drop_index("ix_delivery_notes_delivery_number", table_name="delivery_notes")
    op.drop_index("ix_delivery_notes_document_id", table_name="delivery_notes")
    op.drop_table("delivery_notes")
