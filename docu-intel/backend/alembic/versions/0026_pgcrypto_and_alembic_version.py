"""Bundle two pieces of bootstrap that are easy to forget on a fresh
``pgvector/pgvector:pg16`` install and that, if missed, make later
Sprint 1 migrations crash in non-obvious ways.

1. ``pgcrypto`` extension
   Migration 0027 (``0027_integration_clients_key_id``) uses
   ``gen_random_bytes(8)`` to backfill ``integration_clients.key_id``.
   ``gen_random_bytes`` lives in the ``pgcrypto`` extension. The
   ``pgvector/pgvector:pg16`` image ships the extension available
   but does not enable it by default, so the migration fails with
   ``function gen_random_bytes(integer) does not exist`` on every
   fresh install. We enable it here once, idempotently, and 0027
   is free to keep its own ``CREATE EXTENSION IF NOT EXISTS``
   as belt-and-braces.

2. ``alembic_version.version_num`` column width
   Alembic creates ``alembic_version`` with ``version_num VARCHAR(32)``.
   Several Sprint 1+ migration revision ids are longer than 32
   characters, e.g. ``0028_tenant_default_permissive_group`` (34)
   and ``0029_normalized_doc_number_columns`` (34). When the
   migration that follows them tries to UPDATE ``alembic_version``
   to its own id, Postgres rejects the value with
   ``value too long for type character varying(32)`` and the
   whole transactional DDL chain rolls back. We widen the column
   to ``VARCHAR(64)`` here, well clear of any id in the project.

Both changes are forward-only by design:

* Dropping ``pgcrypto`` is unsafe (the rest of the app uses it for
  ``gen_random_uuid`` / ``digest``) and would surprise an operator
  who has come to rely on it. We leave it installed.
* Shrinking ``alembic_version.version_num`` would fail as soon as
  any longer-id migration is still applied. The downgrade is a
  documented no-op.

Both are no-ops in SQLite (used by the test suite via
``sqlite+pysqlite:///:memory:``) because the operations are
Postgres-specific.
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0026_pgcrypto_and_alembic_version"
down_revision = "0025_ocr_engine_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable pgcrypto and widen the alembic version column."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite: pgcrypto doesn't exist and the alemic_version column
        # type is a free-form string anyway. Nothing to do.
        return

    # 1. pgcrypto. ``IF NOT EXISTS`` keeps this idempotent on
    #    environments that already enable the extension via their
    #    own bootstrap (e.g. a custom ``initdb`` script).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 2. Widen ``alembic_version.version_num`` from VARCHAR(32) to
    #    VARCHAR(64). Postgres treats this as an in-place type
    #    change (no table rewrite) because VARCHAR widening is a
    #    binary-coercible no-op. Idempotent: a re-run leaves the
    #    column at 64.
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE VARCHAR(64)"
    )


def downgrade() -> None:
    """Forward-only by design — see module docstring."""
    # Intentionally empty: see the rationale at the top of the file.
    pass
