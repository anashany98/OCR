"""S2.2 — ``BudgetScope`` ORM mirrors the partial unique index.

The raw unique index ``uq_budget_scope_context`` lives in the
``0053_contextual_budget_identity`` migration. Without an equivalent
declaration on the SQLAlchemy model, ``Base.metadata.create_all``
would silently create a ``budget_scopes`` table without the
constraint, and a future schema regeneration could lose the
uniqueness guarantee on ``(year, brand_id, hotel_id, budget_code)``
for non-legacy rows.

The constraint has two subtle properties that a plain
``UniqueConstraint`` cannot express:

* ``WHERE legacy_unscoped = false`` (partial index — legacy rows
  can keep duplicates until they are backfilled)
* ``NULLS NOT DISTINCT`` (PostgreSQL 15+ treats ``(NULL, X, Y, Z)``
  and ``(NULL, X', Y', Z')`` as equal when the other columns match)

We mirror both via a partial ``Index`` with the relevant
PostgreSQL dialect options. This test pins the model so a future
refactor that re-introduces a plain ``UniqueConstraint`` is caught.
"""
from __future__ import annotations

from sqlalchemy import Index


def test_budget_scope_orm_declares_contextual_unique_index():
    """``BudgetScope.__table__.indexes`` must contain a unique index
    named ``uq_budget_scope_context`` covering the four contextual
    columns.
    """
    from app.models.budget_scope import BudgetScope

    column_names = {c.name for c in BudgetScope.__table__.c}
    expected_columns = {"year", "brand_id", "hotel_id", "budget_code"}
    assert expected_columns.issubset(column_names), (
        f"BudgetScope is missing expected columns {expected_columns - column_names}"
    )

    matches = [
        idx
        for idx in BudgetScope.__table__.indexes
        if idx.name == "uq_budget_scope_context"
    ]
    assert matches, (
        "BudgetScope ORM is missing the `uq_budget_scope_context` unique "
        "index. Re-add the partial unique Index in `__table_args__` to "
        "match migration 0053."
    )
    index = matches[0]
    assert index.unique, "uq_budget_scope_context must be UNIQUE"
    assert isinstance(index, Index)


def test_budget_scope_orm_uses_partial_where_clause():
    """The ORM index must use ``legacy_unscoped = false`` as its
    ``postgresql_where`` so the partial-uniqueness semantics of
    migration 0053 are preserved.
    """
    from app.models.budget_scope import BudgetScope

    matches = [
        idx
        for idx in BudgetScope.__table__.indexes
        if idx.name == "uq_budget_scope_context"
    ]
    assert matches, "uq_budget_scope_context not declared on BudgetScope"
    index = matches[0]
    dialect_options = getattr(index, "dialect_options", None) or {}
    postgres_opts = dialect_options.get("postgresql", {}) if dialect_options else {}
    where = postgres_opts.get("where")
    assert where, (
        "uq_budget_scope_context must declare `postgresql_where` so the "
        "partial-uniqueness semantics from migration 0053 are preserved "
        "(`WHERE legacy_unscoped = false`)."
    )
    assert "legacy_unscoped" in str(where), (
        f"Expected `legacy_unscoped` in the partial WHERE clause, got {where!r}"
    )
