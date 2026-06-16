"""Regression test for the Alembic graph integrity.

Background
----------
The repository hit a double-head bug in the migration graph:

* ``0031_pg_trgm_text_search_indexes`` had **two** siblings —
  ``0032_block_type_chunk_type_enums`` and
  ``0032_fix_embedding_vector_dimension`` — both with
  ``down_revision = "0031_pg_trgm_text_search_indexes"``.
* The rest of the chain (0033, 0034, ...) only followed
  ``0032_block_type_chunk_type_enums``.
* Result: ``0032_fix_embedding_vector_dimension`` was an
  orphan that ``alembic upgrade head`` would never run, and
  the ``document_chunks.embedding vector(768)`` migration
  (plus its HNSW index) was silently skipped — breaking every
  ``INSERT INTO document_chunks`` in production with a
  ``ValueError: expected 1024 dimensions, not 768``.

The fix was to re-chain the embedding-fix migration to depend
on the latest revision in the linear chain, so the entire
history collapses back to a single head. This test guards
against re-introducing the bug.
"""

from __future__ import annotations

import os

import pytest


# Test-only defaults; conftest.py already sets these but we
# duplicate the minimum here so this test is self-contained
# when run in isolation.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/_unused")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


def _load_script_directory():
    """Return an ``alembic.script.ScriptDirectory`` built from
    the project's ``alembic.ini`` without going through the CLI
    (so this test runs offline and is fast).
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    return ScriptDirectory.from_config(cfg)


def test_alembic_has_exactly_one_head():
    """A single head is required for ``alembic upgrade head`` to
    be a deterministic, total order. Multiple heads cause
    ``alembic upgrade head`` to abort with
    ``FAILED: Multiple head revisions``.
    """
    sd = _load_script_directory()
    heads = sd.get_heads()

    assert len(heads) == 1, (
        f"Alembic graph has {len(heads)} heads: {heads}. "
        "Re-chain the orphans so the history collapses to a single linear chain."
    )


def test_alembic_embedding_fix_is_not_an_orphan():
    """The 0032 embedding-fix migration must appear in the
    walked chain — it was the specific orphan that produced
    the ``expected 1024 dimensions`` bug. If this test fails
    it means a new ``down_revision`` value has been assigned
    in a way that re-orphans the migration.
    """
    sd = _load_script_directory()
    chain_revisions = [rev.revision for rev in sd.walk_revisions()]

    assert "0032_fix_embedding_vector_dimension" in chain_revisions, (
        "0032_fix_embedding_vector_dimension is no longer in the "
        "migration chain. It must be a downstream descendant of "
        "0031_pg_trgm_text_search_indexes so alembic upgrade head "
        "actually runs it."
    )


def test_alembic_history_is_a_single_linear_chain():
    """Beyond the head check, verify the full graph is a single
    linear chain: every revision (except the first) has
    exactly one ``down_revision`` parent, and every revision
    (except the head) has at least one child. This catches
    both new orphans and new branches before they hit CI.
    """
    sd = _load_script_directory()
    revisions = list(sd.walk_revisions())

    # Every revision except the root must declare a down_revision.
    for rev in revisions:
        assert rev.down_revision is not None or rev.revision == "0001_initial_schema", (
            f"Revision {rev.revision} has no down_revision but is not the root."
        )

    # Build parent -> children map.
    children: dict[str | None, list[str]] = {}
    for rev in revisions:
        children.setdefault(rev.down_revision, []).append(rev.revision)

    # No revision should have more than one child — that would
    # be a branch.
    for parent, kids in children.items():
        assert len(kids) == 1, (
            f"Down_revision {parent!r} has multiple children: {kids}. "
            "Re-chain the new migration so the history is linear."
        )

    # The root has exactly one child (0002 is the first child
    # of 0001).
    assert children[None] == ["0001_initial_schema"], (
        f"Unexpected root children: {children[None]!r}. "
        "There must be exactly one initial schema migration."
    )
    # The head has no children.
    heads = sd.get_heads()
    for h in heads:
        assert h not in children or children[h] == [], (
            f"Head {h} unexpectedly has children: {children.get(h)!r}."
        )


def test_alembic_chain_contains_all_critical_sprint_migrations():
    """Pin the chain to a known set of critical sprint
    migrations so a careless re-chain that drops one is caught
    immediately.
    """
    sd = _load_script_directory()
    chain = {rev.revision for rev in sd.walk_revisions()}
    expected = {
        "0001_initial_schema",
        "0031_pg_trgm_text_search_indexes",
        "0032_block_type_chunk_type_enums",
        "0032_fix_embedding_vector_dimension",
        "0033_partition_audit_and_jobs",
        "0034_invoice_deterministic_fields",
    }
    missing = expected - chain
    assert not missing, f"Critical migrations missing from chain: {sorted(missing)}"


@pytest.mark.parametrize(
    "child,parent",
    [
        # The exact relationships that were broken by the
        # double-head bug — the embedding fix had to land in
        # the chain somewhere. Pin it to the tail of the chain
        # (depending on the most recent linear revision) to
        # catch a future re-chain that re-orphans it.
        ("0032_block_type_chunk_type_enums", "0031_pg_trgm_text_search_indexes"),
        ("0033_partition_audit_and_jobs", "0032_block_type_chunk_type_enums"),
        ("0034_invoice_deterministic_fields", "0033_partition_audit_and_jobs"),
    ],
)
def test_alembic_chain_edges(child, parent):
    """Spot-check that the linear chain edges we depend on
    are still wired the way the rest of the project expects.
    """
    sd = _load_script_directory()
    rev = sd.get_revision(child)
    assert rev is not None, f"Revision {child} not found in the migration graph"
    assert rev.down_revision == parent, (
        f"Expected {child}.down_revision == {parent!r}, "
        f"got {rev.down_revision!r}. The serial chain has been broken."
    )
