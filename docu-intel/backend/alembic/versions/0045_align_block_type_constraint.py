"""0045 — Align block_type CHECK constraint with ORM allowed types.

The CHECK constraint from 0032 only allows 6 block types, but the ORM
model (DocumentBlock._ALLOWED_BLOCK_TYPES) accepts 18. PP-Structure
and other OCR adapters can produce any of the 18, causing constraint
violations on insert. This migration drops the old CHECK and recreates
it with the full set.

Revision ID: 0045_align_block_type_constraint
Revises: 0044_drop_mv_active_documents
Create Date: 2026-07-10
"""
from alembic import op

revision = "0045_align_block_type_constraint"
down_revision = "0044_drop_mv_active_documents"
branch_labels = None
depends_on = None

# Single source of truth — must match DocumentBlock._ALLOWED_BLOCK_TYPES.
_ALL_BLOCK_TYPES: tuple[str, ...] = (
    "text", "table", "figure", "header", "footer", "list",
    "doc_title", "reference", "seal", "table_title", "figure_title",
    "table_footnote", "text_region", "formula", "chart", "equation",
    "code", "caption",
)


def _sql_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # Sanitise any existing rows with out-of-set values.
    op.execute(
        "UPDATE document_blocks SET block_type = 'text' "
        "WHERE block_type NOT IN " + _sql_list(_ALL_BLOCK_TYPES)
    )
    # Drop old constraint if it exists.
    op.execute("ALTER TABLE document_blocks DROP CONSTRAINT IF EXISTS ck_document_blocks_block_type")
    # Recreate with the full set.
    op.create_check_constraint(
        "ck_document_blocks_block_type",
        "document_blocks",
        "block_type IN " + _sql_list(_ALL_BLOCK_TYPES),
    )


def downgrade() -> None:
    # Restore the original 6-type constraint from 0032.
    _ORIGINAL_TYPES: tuple[str, ...] = ("text", "table", "figure", "header", "footer", "list")
    op.execute(
        "UPDATE document_blocks SET block_type = 'text' "
        "WHERE block_type NOT IN " + _sql_list(_ORIGINAL_TYPES)
    )
    op.execute("ALTER TABLE document_blocks DROP CONSTRAINT IF EXISTS ck_document_blocks_block_type")
    op.create_check_constraint(
        "ck_document_blocks_block_type",
        "document_blocks",
        "block_type IN " + _sql_list(_ORIGINAL_TYPES),
    )
