"""Shared pytest fixtures and env configuration.

Ensures tests can import the app without the production settings validator
rejecting the local development .env. The CI environment provides real
credentials via env vars.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

# Only set defaults if not already provided (so CI env wins)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:TestPasswordStrong2026Secure@postgres:5432/docuintel")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")


_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "openapi.public-paths.json"
)


def pytest_addoption(parser):
    """Add a flag to regenerate the OpenAPI public-routes snapshot."""
    parser.addoption(
        "--update-snapshot",
        action="store_true",
        default=False,
        help="Rewrite docs/openapi.public-paths.json with the current public routes.",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-tag contract tests so they can be run separately."""
    for item in items:
        if "openapi_contract" in item.nodeid:
            item.add_marker(pytest.mark.contract)

    # OPS-2 / P2 repair: the OCR cascade depends on the
    # ``tesseract`` binary being on PATH. CI installs it via
    # apt-get, but local Windows / macOS dev machines often
    # don't have it. We auto-skip OCR tests (anything whose
    # path mentions ``test_ocr`` or that the test itself
    # marks with ``@pytest.mark.requires_tesseract``) so the
    # local run is still useful and CI stays the source of
    # truth for the OCR pipeline.
    if shutil.which("tesseract") is None:
        skip = pytest.mark.skip(reason="tesseract binary not on PATH (CI-only test)")
        for item in items:
            if "test_ocr" in item.nodeid or "ocr_pipeline" in item.nodeid:
                item.add_marker(skip)


@pytest.fixture
def public_routes_snapshot(request):
    """Return the frozen public-routes snapshot, regenerating it if requested."""
    from app.main import app  # local import: needs env defaults above
    from test_openapi_contract import _collect_public_routes  # noqa: WPS433

    current = _collect_public_routes(app)
    if request.config.getoption("--update-snapshot"):
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT_PATH.write_text(
            json.dumps(
                {"_comment": "Frozen public API routes.", "routes": current},
                indent=2,
            ),
            encoding="utf-8",
        )
        return current
    return current

