"""M9 (Sprint 4): Add pg_trgm GIN indexes for ILIKE text search.

The text search path in ``search_service.search_text`` uses
``ILIKE '%query%'`` on ``document_pages.text`` and
``document_blocks.text``.  Without a trigram index these are
sequential scans.  Adding a GIN index with ``pg_trgm_ops`` lets
PostgreSQL use the trigram similarity to narrow the scan
dramatically.

The ``pg_trgm`` extension is already created in migration 0001.
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0031_pg_trgm_text_search_indexes"
down_revision = "0030_updated_at_documents_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN index on document_pages.text for ILIKE substring search.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_pages_text_trgm "
        "ON document_pages USING GIN (text gin_trgm_ops)"
    )
    # GIN index on document_blocks.text for ILIKE substring search.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_blocks_text_trgm "
        "ON document_blocks USING GIN (text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_blocks_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_document_pages_text_trgm")
