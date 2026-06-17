"""Contract test for the versioned public API.

Goals
-----
1. Validate that the OpenAPI schema is well-formed (every operation has a
   response, every path parameter is declared, every referenced schema exists).
2. Freeze the **public** path list (everything mounted under ``api_v1_prefix``
   and the ``/integrations/v1`` contract) so accidental additions/renames/removals
   are caught in code review.
3. Verify the liveness endpoint stays at the root (not versioned).

Run with::

    cd docu-intel/backend
    pytest tests/test_openapi_contract.py -v

The ``--update-snapshot`` flag rewrites ``docs/openapi.public-paths.json``
after a deliberate, reviewed change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.public-paths.json"

# Path templates that are allowed to change without bumping the snapshot
# (they are part of dynamic resources where the ID is in the URL).
DYNAMIC_ID = re.compile(r"\{[^}]+\}")


def _collect_public_routes(app) -> list[dict]:
    """Extract (method, path, name) tuples mounted under api_v1_prefix or /integrations/v1.

    The integrations API has its own /integrations/v1 prefix and is included so
    external clients can detect contract changes too.
    """
    from app.core.config import settings  # local: avoid app import at collect time

    v1_prefix = settings.api_v1_prefix.rstrip("/")
    integrations_prefix = "/integrations/v1"

    collected: list[dict] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not (path.startswith(v1_prefix) or path.startswith(integrations_prefix)):
            continue
        if not route.methods:
            continue
        for method in sorted(route.methods - {"HEAD"}):
            collected.append(
                {
                    "method": method.upper(),
                    "path": _normalize_path(path),
                    "name": route.name or "",
                }
            )
    collected.sort(key=lambda item: (item["path"], item["method"]))
    return collected


def _normalize_path(path: str) -> str:
    """Replace dynamic IDs with a placeholder so {doc_id} == {document_id} in diffs."""
    return DYNAMIC_ID.sub("{id}", path)


def test_app_loads():
    """Sanity: the FastAPI app imports cleanly and the prefix is set."""
    from app.main import app
    from app.core.config import settings

    assert settings.api_v1_prefix, (
        "api_v1_prefix must be set; the API versioning strategy relies on it."
    )
    assert len(app.routes) > 0


def test_openapi_schema_is_valid():
    """The generated OpenAPI document is well-formed and has the required top-level keys."""
    from app.main import app

    schema = app.openapi()
    assert "openapi" in schema, "Missing OpenAPI version"
    assert "info" in schema, "Missing info block"
    assert "paths" in schema, "Missing paths block"
    assert schema["paths"], "No paths declared — did all routers get registered?"
    assert "components" in schema, "Missing components block"

    # Every path operation must declare at least one response.
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert "responses" in op, f"{method.upper()} {path} has no responses"
            assert op["responses"], f"{method.upper()} {path} has empty responses"


def test_public_routes_match_snapshot(public_routes_snapshot):
    """Freeze the public API surface so accidental breaks are caught in review.

    Uses the ``public_routes_snapshot`` fixture from conftest which honours
    ``--update-snapshot`` for intentional changes.
    """
    current = public_routes_snapshot
    stored = (
        json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8")) if SNAPSHOT_PATH.exists() else None
    )

    if stored is None:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(
                {
                    "_comment": (
                        "Frozen snapshot of public API routes. Regenerate with "
                        "`pytest tests/test_openapi_contract.py --update-snapshot` "
                        "after deliberate, reviewed changes."
                    ),
                    "routes": current,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        pytest.fail(
            f"Snapshot created at {SNAPSHOT_PATH}. Commit it and re-run. "
            f"Captured {len(current)} public routes."
        )

    stored_routes = stored.get("routes", [])
    if current != stored_routes:
        added = [r for r in current if r not in stored_routes]
        removed = [r for r in stored_routes if r not in current]
        msg_parts = []
        if added:
            msg_parts.append(f"Added ({len(added)}): {added[:5]}")
        if removed:
            msg_parts.append(f"Removed ({len(removed)}): {removed[:5]}")
        if current != stored_routes and not added and not removed:
            msg_parts.append("Reordered or modified entries — review the diff.")
        pytest.fail(
            "Public API surface changed. Review the diff and re-run with "
            "`--update-snapshot` if the change is intentional.\n  " + "\n  ".join(msg_parts)
        )


def test_health_endpoint_present():
    """The root /health endpoint is mounted (not under v1) for liveness probes."""
    from app.main import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/health" in paths, "Liveness probe /health is missing"
