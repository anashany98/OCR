"""S1.10 follow-up — SQL-layer scope enforcement contract.

The :mod:`test_search_scope_contract` module checks that every public
search endpoint at least calls the post-filter
``filter_search_results_for_scope`` as defense-in-depth. This test goes
one step further: for the row-based exact and guided endpoints, we
require ``apply_access_predicates`` to be called **before** the
``LIMIT`` so a low ``limit`` value cannot consume the page with rows
the user is not allowed to see.

The test is structural (reads the file from disk) and does not need
a running DB. It is intentionally strict: a future refactor that
moves scope enforcement back to the post-filter would silently
re-introduce the M-12 leak that this guard was created to fix.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# Routes that hit the row tables (Budget/Order/DocumentEntity) and
# therefore must enforce the access scope at the SQL layer. The
# text-only ``/text`` and the vector ``/semantic``/``/hybrid``
# already enforce scope inside the search service.
ROW_BASED_ROUTES: dict[str, tuple[str, ...]] = {
    "exact_search": (
        "apply_access_predicates(stmt, scope).limit(limit)",
    ),
    "guided_search": (
        "search_text(db, normalized, limit=limit, access_scope=scope)",
        "apply_access_predicates(stmt, scope).limit(limit)",
    ),
}

SEARCH_ROUTE_PATH = Path("app/api/routes/search.py")


def _function_body(name: str) -> str:
    """Return the source of the named top-level ``def`` from the
    search route file.

    We parse the file manually (simple state machine) instead of using
    ``inspect.getsource`` because the test runs after the module has
    been imported once and Python's bytecode cache can mask edits
    made between import and test run. Reading the file directly
    avoids that pitfall.
    """
    text = SEARCH_ROUTE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    body: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith(f"def {name}(") or line.startswith(f"async def {name}("):
            in_target = True
            body.append(line)
            continue
        if in_target:
            if line and not line[0].isspace() and line.startswith("def "):
                break
            body.append(line)
    if not in_target:
        pytest.fail(f"def {name} not found in {SEARCH_ROUTE_PATH}")
    return "\n".join(body)


@pytest.mark.parametrize("function_name,required_substrings", list(ROW_BASED_ROUTES.items()))
def test_row_based_route_enforces_scope_in_sql(function_name, required_substrings):
    """Each row-based search route must apply the access scope at the
    SQL layer (before the LIMIT) so a restricted user does not lose
    in-scope rows to out-of-scope rows that consumed the page cap.
    """
    body = _function_body(function_name)
    missing = [snippet for snippet in required_substrings if snippet not in body]
    assert not missing, (
        f"app/api/routes/search.py:{function_name} is missing the SQL-layer scope "
        f"guard(s) {missing}. Re-apply the fix: use "
        f"`apply_access_predicates(stmt, scope)` before `.limit(limit)` "
        f"(and pass `access_scope=scope` to `search_text`). See plan "
        f"`docu-intel/docs/PLAN_MAESTRO_MEJORAS.md` 1.1."
    )


def test_exact_search_does_not_apply_limit_before_scope():
    """Regression guard: ``/exact`` must not call ``.limit(limit)`` on
    a statement that has not yet been filtered by the access scope.

    The pattern we forbid is the SQLAlchemy fluent chain
    ``.where(<predicate>).limit(limit)`` on a single line with no
    intervening ``apply_access_predicates``. We split the source on
    statement boundaries (``stmt = ...``) and only flag chains that
    are not interrupted by the scope predicate.
    """
    body = _function_body("exact_search")
    bad_pattern = re.compile(r"\.where\([^)]*\)\s*\.limit\(limit\)")
    statements = re.split(r"\n\s*stmt\s*=\s*", body)
    for statement in statements[1:]:
        if "apply_access_predicates" in statement:
            continue
        matches = bad_pattern.findall(statement)
        assert not matches, (
            "exact_search has a `.where(...).limit(limit)` chain in a "
            "statement that does not call `apply_access_predicates` "
            "first. The LIMIT must run AFTER the scope filter so "
            "out-of-scope rows do not consume the page. Offending "
            "statement: " + statement.strip()
        )


def test_guided_search_does_not_apply_limit_before_scope():
    """Same regression guard as ``exact_search`` but for ``/guided``."""
    body = _function_body("guided_search")
    bad_pattern = re.compile(r"\.where\([^)]*\)\s*\.limit\(limit\)")
    statements = re.split(r"\n\s*stmt\s*=\s*", body)
    for statement in statements[1:]:
        if "apply_access_predicates" in statement:
            continue
        matches = bad_pattern.findall(statement)
        assert not matches, (
            "guided_search has a `.where(...).limit(limit)` chain in a "
            "statement that does not call `apply_access_predicates` "
            "first. Offending statement: " + statement.strip()
        )
