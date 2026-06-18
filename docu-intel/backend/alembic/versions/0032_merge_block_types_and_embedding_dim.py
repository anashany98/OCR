"""Merge 0032 heads: block_type/chunk_type enums + embedding dimension fix.

Two parallel migrations were created against the same parent
``0031_pg_trgm_text_search_indexes``:

* ``block_type_chunk_type_enums``    -> CHECK constraints on
  ``document_blocks.block_type`` and ``document_chunks.chunk_type``
  so a typo (``"textt"``) cannot silently zero a filter result.

* ``fix_embedding_vector_dimension`` -> ``vector(1024)`` -> ``vector(768)``
  so the deployed ``nomic-embed-text:v1.5`` model (768d) can actually
  insert rows instead of failing every extraction job with
  ``expected 1024 dimensions, not 768``.

Both are independent schema changes that need to land together before
the next ``0033_*`` migration can chain off a single head. This single
file replaces both so alembic only sees one head at ``0032``.

The original two files were deleted from disk; this merged file is the
new unique ``0032`` revision. Because the backend has been failing to
boot since these were authored (multiple-heads error), neither half
has ever been applied to a live database, so the merge is safe — a
fresh ``alembic upgrade head`` runs the combined upgrade exactly once.

Order matters: data sanitisation and CHECK constraints run first (the
CHECK on ``chunk_type`` does not touch the ``embedding`` column so it
is independent of the dimension change), then the HNSW index is
dropped, the column is altered, and the index is recreated. Downgrade
reverses the same steps in reverse.
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0032_merge_block_types_and_embedding_dim"
down_revision = "0031_pg_trgm_text_search_indexes"
branch_labels = None
depends_on = None


# Documented sets. Keep in sync with the docstrings on
# ``DocumentBlock.block_type`` and ``DocumentChunk.chunk_type`` in
# ``app/models/document.py``. Adding a value here is a schema
# change: existing rows with the new value will be accepted on
# INSERT / UPDATE; a rollback reverts the constraint and the
# old rows would fail a re-add unless they have been sanitised
# back to the original set.
_DOCUMENT_BLOCK_TYPES: tuple[str, ...] = (
    "text",
    "table",
    "figure",
    "header",
    "footer",
    "list",
)
_DOCUMENT_CHUNK_TYPES: tuple[str, ...] = (
    "text",
    "table",
    "heading",
    "code",
)


def _sql_list(values: tuple[str, ...]) -> str:
    """Render a Python tuple of strings as a SQL ``('a', 'b')``
    list. The values are trusted constants (this module is not
    a path for operator input), so we use Python's repr-style
    quoting via ``str.replace`` to avoid pulling in a full SQL
    escape helper.
    """
    quoted = ", ".join(f"'{v}'" for v in values)
    return "(" + quoted + ")"


def upgrade() -> None:
    bind = op.get_bind()

    # --- block_type / chunk_type CHECK constraints ----------------------
    # Sanitise any existing rows that have an out-of-set value.
    # The historical default for both columns is ``"text"``, so
    # we map anything else to ``"text"`` rather than deleting
    # the row. Operators who want the new values back can fix
    # the data manually before rolling forward again.
    op.execute(
        "UPDATE document_blocks SET block_type = 'text' "
        "WHERE block_type NOT IN " + _sql_list(_DOCUMENT_BLOCK_TYPES)
    )
    op.execute(
        "UPDATE document_chunks SET chunk_type = 'text' "
        "WHERE chunk_type NOT IN " + _sql_list(_DOCUMENT_CHUNK_TYPES)
    )

    # Add the CHECK constraints. We use the ``IF NOT EXISTS``
    # pattern via a lookup query because Alembic's
    # ``create_check_constraint`` does not have a portable
    # ``IF NOT EXISTS`` flag and the constraint may already
    # exist on a deployment that was hand-patched.
    inspector = op.get_bind().dialect.inspector(bind)  # type: ignore[attr-defined]
    if "document_blocks" in inspector.get_table_names():
        existing = {
            c["name"] for c in inspector.get_check_constraints("document_blocks")
        }
        if "ck_document_blocks_block_type" not in existing:
            op.create_check_constraint(
                "ck_document_blocks_block_type",
                "document_blocks",
                "block_type IN " + _sql_list(_DOCUMENT_BLOCK_TYPES),
            )
    if "document_chunks" in inspector.get_table_names():
        existing = {
            c["name"] for c in inspector.get_check_constraints("document_chunks")
        }
        if "ck_document_chunks_chunk_type" not in existing:
            op.create_check_constraint(
                "ck_document_chunks_chunk_type",
                "document_chunks",
                "chunk_type IN " + _sql_list(_DOCUMENT_CHUNK_TYPES),
            )

    # --- embedding dimension fix (1024 -> 768) --------------------------
    # Drop the HNSW index first (it depends on the old vector type).
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    # Alter the column type from vector(1024) to vector(768).
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(768)"
    )
    # Recreate the HNSW index with the new dimension.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    # --- reverse embedding dimension (768 -> 1024) ---------------------
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(1024)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )

    # --- drop CHECK constraints ----------------------------------------
    op.drop_constraint(
        "ck_document_blocks_block_type", "document_blocks", type_="check"
    )
    op.drop_constraint(
        "ck_document_chunks_chunk_type", "document_chunks", type_="check"
    )
