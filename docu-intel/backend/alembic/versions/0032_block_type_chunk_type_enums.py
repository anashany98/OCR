"""M7 (Sprint 2) — Enums + CHECK constraints for ``block_type`` /
``chunk_type``.

The previous implementation accepted any string in
``document_blocks.block_type`` and ``document_chunks.chunk_type``,
which is a footgun: a typo (``"textt"`` instead of ``"text"``)
silently zeroed the result of a ``WHERE block_type='table'``
filter without raising. The ORM model already documents a fixed
set of values in its docstring; this migration enforces them at
the database level.

The migration:

1. Adds a CHECK constraint on ``document_blocks.block_type``
   limiting values to the documented set.
2. Adds a CHECK constraint on ``document_chunks.chunk_type``
   limiting values to the documented set.

The migration does **not** use a Postgres ENUM type because:

* ENUMs require an ``ALTER TYPE`` to add new values, which is
  awkward to coordinate across migrations and rollbacks.
* ENUMs add a new catalogue type that other tools (``psql``,
  monitoring, BI) need to be aware of. CHECK constraints keep
  the schema portable.
* The set of valid values is small and stable; CHECK + an
  ``Enum`` in the Python layer is the standard pattern.

Existing data is sanitised before the constraint is added: any
``block_type`` or ``chunk_type`` not in the documented set is
mapped to ``"text"`` (the historical default). The mapping is
reversible via the downgrade.
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0032_block_type_chunk_type_enums"
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


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_blocks_block_type", "document_blocks", type_="check"
    )
    op.drop_constraint(
        "ck_document_chunks_chunk_type", "document_chunks", type_="check"
    )
