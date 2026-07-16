"""S2.1 — Rate limit coverage for ``/documents`` and ``/search/guided``.

The previous deployment left the public document routes without a
``@limiter.limit`` decorator, which meant a single client could
hammer ``/upload`` or ``/reprocess`` without throttling. This test
pins the decorator presence on each sensitive endpoint so a future
refactor that drops the decorator is caught by CI.

The test is structural (reads the route file from disk) and does
not need a running app or Redis instance. Slowapi's actual rate
enforcement is exercised by the integration test suite; here we
only assert the *contract* that every sensitive endpoint has a
limit configured.
"""
from __future__ import annotations

from pathlib import Path

import pytest


DOCUMENTS_PATH = Path("app/api/routes/documents.py")
SEARCH_PATH = Path("app/api/routes/search.py")


# Map of (file basename, endpoint function name) → required limit string.
# The values are the ``"N/period"`` strings we expect to find on
# the decorator immediately above the function. We check the
# function body, not the file as a whole, so a duplicate limit on
# an unrelated function does not satisfy the test.
EXPECTED_LIMITS: dict[tuple[str, str], str] = {
    ("documents.py", "upload_document"): "30/minute",
    ("documents.py", "upload_batch"): "10/minute",
    ("documents.py", "list_documents"): "120/minute",
    ("documents.py", "reprocess_bulk"): "10/minute",
    ("documents.py", "reclassify_documents"): "10/minute",
    ("documents.py", "get_document"): "120/minute",
    ("documents.py", "get_document_pages"): "120/minute",
    ("documents.py", "get_document_page_image"): "120/minute",
    ("documents.py", "get_document_blocks"): "120/minute",
    ("documents.py", "get_document_entities"): "120/minute",
    ("documents.py", "reprocess"): "10/minute",
    ("documents.py", "delete_document"): "30/minute",
    ("documents.py", "download_document"): "30/minute",
    ("search.py", "guided_search"): "60/minute",
}


def _resolve_path(basename: str) -> Path:
    if basename == "documents.py":
        return DOCUMENTS_PATH
    if basename == "search.py":
        return SEARCH_PATH
    raise ValueError(f"Unknown test path: {basename}")


def _decorator_above_function(path: Path, function_name: str) -> str:
    """Return the source lines immediately above ``def <name>(`` so
    we can check for ``@limiter.limit(...)``.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"def {function_name}(") or line.startswith(
            f"async def {function_name}("
        ):
            # Walk backwards over the maximum plausible decorator
            # block (router + limiter + 8 generic lines of docstring
            # is unrealistic but cheap to scan).
            return "\n".join(lines[max(0, index - 8):index])
    pytest.fail(f"def {function_name} not found in {path}")


@pytest.mark.parametrize(
    "basename,function_name,expected_limit",
    [(k[0], k[1], v) for k, v in EXPECTED_LIMITS.items()],
)
def test_endpoint_has_rate_limit(basename, function_name, expected_limit):
    """The named endpoint must have a ``@limiter.limit(...)``
    decorator configured with the expected ``"N/period"`` value.
    """
    path = _resolve_path(basename)
    decorator = _decorator_above_function(path, function_name)
    assert "@limiter.limit" in decorator, (
        f"{path}:{function_name} is missing a @limiter.limit decorator. "
        f"Add one (see PLAN_MAESTRO_MEJORAS.md 2.1)."
    )
    assert expected_limit in decorator, (
        f"{path}:{function_name} has a @limiter.limit but the rate "
        f"({expected_limit!r}) is not present in the decorator. "
        f"Decorator was:\n{decorator}"
    )
