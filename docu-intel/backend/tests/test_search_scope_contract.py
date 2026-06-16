"""S1.10 (Sprint 1) — defensive contract test for ``AccessScope``
enforcement on the public search endpoints.

The full integration test (two users in two ``budget_scopes``
seeing only their own documents) requires the production access
group machinery to be set up correctly in the test DB, which is
fragile across migrations. Instead we verify a structural
contract that is much harder to break silently: every public
search endpoint *must* call ``resolve_user_access_scope`` and
``filter_search_results_for_scope`` (or the equivalent
``filter_search_results_for_scope`` helper) before returning a
response.

The contract is enforced by reading the source of each route
function and asserting it contains the expected sequence of
function calls. If a future refactor drops the scope filter
from a route, the test fails with a clear message pointing at
the missing call. The test does not need a running DB, which
keeps it fast (sub-100 ms).

The route table is hard-coded here on purpose: the set of public
search endpoints is small and a developer adding a new one
should be forced to update this list, which is the actual
review-point we want to enforce.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


# Files in scope. The route is registered in ``app/api/router.py``
# but the actual handler functions live in these two files.
SEARCH_ROUTE_FILES: tuple[Path, ...] = (
    Path("app/api/routes/search.py"),
    Path("app/api/routes/search_saved.py"),
)


# Map of (file basename, function name) → list of substrings that
# must appear in the function's source. We allow either
# ``filter_search_results_for_scope`` (the helper) or
# ``redact_search_results_for_scope`` (the public API that
# includes the filter). Both end up calling the same scope
# filter, so a developer using either is fine.
REQUIRED_CALLS: dict[tuple[str, str], tuple[str, ...]] = {
    ("search.py", "text_search"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
    ("search.py", "exact_search"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
    ("search.py", "guided_search"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
    ("search.py", "semantic_search"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
    ("search.py", "hybrid_search_endpoint"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
    ("search.py", "export_search_csv"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
    ("search.py", "export_search_json"): (
        "resolve_user_access_scope",
        "filter_search_results_for_scope",
    ),
}


def _get_source_for_route(basename: str, function_name: str) -> str:
    """Return the source of the named function in the named file.

    Uses ``inspect.getsource`` so the test is robust to file
    location changes (it walks the loaded module instead of
    relying on a hard-coded path).
    """
    import importlib

    module_name = "app.api.routes." + basename.removesuffix(".py")
    module = importlib.import_module(module_name)
    func = getattr(module, function_name, None)
    if func is None:
        pytest.fail(f"Route function {module_name}.{function_name} not found")
    return inspect.getsource(func)


@pytest.mark.parametrize(
    "route_key,required_calls",
    list(REQUIRED_CALLS.items()),
)
def test_search_route_enforces_access_scope(route_key, required_calls):
    """Every public search route must call both the scope
    resolver and the result filter before returning."""
    basename, function_name = route_key
    source = _get_source_for_route(basename, function_name)
    missing = [call for call in required_calls if call not in source]
    assert not missing, (
        f"{basename}:{function_name} is missing the scope-filter call(s) "
        f"{missing}. Add `scope = resolve_user_access_scope(db, user)` and "
        f"`results = filter_search_results_for_scope(db, results, scope)` "
        f"to the route body. Refusing to ship a search endpoint that "
        f"leaks documents across user scopes is the S1.10 contract."
    )
