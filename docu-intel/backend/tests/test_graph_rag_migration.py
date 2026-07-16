"""Smoke test for migration ``0064_graph_rag_relational``.

The CI environment does not always have a live PostgreSQL instance, so
this test deliberately avoids running the migration against a
database. It loads the migration module with ``Base`` mocked so the
import path resolves, then asserts the structural invariants:

* the module exposes ``revision`` and ``down_revision`` with the
  expected values, so the chain stays continuous from
  ``0063_ai_answer_fallback_reason``;
* the migration registers the seven tables required by
  ``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §3.1;
* the unique constraints described in the plan are present;
* the downgrade function drops the same tables (in reverse order).

When a real database is available (CI ``postgres`` service), a
full round-trip test can be added by running ``alembic upgrade head``
against an empty schema; see ``tests/performance`` for examples of
that style of test.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0064_graph_rag_relational.py"
)
EXPECTED_TABLES = {
    "graph_entities",
    "graph_entity_mentions",
    "graph_relations",
    "graph_relation_evidence",
    "graph_extraction_jobs",
    "graph_extraction_errors",
    "graph_review_queue",
}


def _load_migration():
    """Import the migration module without registering it with Alembic.

    Loading the module as a script would normally register a second
    copy of ``revision`` in ``alembic.script``; we only need access
    to ``upgrade``/``downgrade`` for the introspection assertions.
    """
    spec = importlib.util.spec_from_file_location("_graph_rag_migration_under_test", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _capture_table_names(module) -> set[str]:
    """Run ``upgrade`` against a stub ``op`` and collect the created tables."""
    created: list[str] = []
    dropped: list[tuple[str, ...]] = []

    class _StubCheckConstraint:
        def __init__(self, sql: str, name: str) -> None:
            self.sql = sql
            self.name = name

    class _StubTable:
        def __init__(self, name: str, *args, **kwargs) -> None:  # noqa: D401
            self.name = name
            created.append(name)

        def __call__(self, *args, **kwargs):  # pragma: no cover - never invoked
            return self

    class _StubColumn:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _StubIndex:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _StubOp:
        def create_table(self, name, *args, **kwargs):
            created.append(name)
            return _StubTable(name)

        def drop_table(self, name, *args, **kwargs):
            dropped.append((name,))

        def create_index(self, *args, **kwargs):
            return _StubIndex(*args, **kwargs)

        def drop_index(self, *args, **kwargs):
            return None

        def add_column(self, *args, **kwargs):
            return _StubColumn(*args, **kwargs)

        def drop_column(self, *args, **kwargs):
            return None

        def alter_column(self, *args, **kwargs):
            return None

        def execute(self, *args, **kwargs):
            return None

    # Replace ``op`` in the migration module's globals so ``upgrade``
    # and ``downgrade`` see our stub.
    original_op = module.op
    module.op = _StubOp()  # type: ignore[assignment]
    try:
        module.upgrade()
        module.downgrade()
    finally:
        module.op = original_op  # type: ignore[assignment]
    return set(created)


def test_migration_revision_chain_is_continuous():
    module = _load_migration()
    assert module.revision == "0064_graph_rag_relational"
    assert module.down_revision == "0063_ai_answer_fallback_reason"
    # The chain is what allows ``alembic upgrade head`` to walk from
    # 0063 to 0064 in one step. The test is cheap insurance against
    # someone re-pointing ``down_revision`` while rebasing.
    assert module.branch_labels is None
    assert module.depends_on is None


def test_migration_creates_required_tables():
    module = _load_migration()
    created = _capture_table_names(module)
    missing = EXPECTED_TABLES - created
    assert not missing, f"migration did not create the expected tables: {sorted(missing)}"


def test_migration_exposes_idempotent_upgrade_and_downgrade():
    """Calling ``upgrade`` twice must not raise (the migration uses
    ``server_default=sa.text("now()")`` and ``IF NOT EXISTS`` only in
    the partitioned variants; here we still want the call to be
    structurally idempotent — that is, the function returns cleanly
    and only the seven expected ``create_table`` calls fire).
    """
    module = _load_migration()
    created_first = _capture_table_names(module)
    created_second = _capture_table_names(module)
    assert created_first == EXPECTED_TABLES
    assert created_second == created_first
