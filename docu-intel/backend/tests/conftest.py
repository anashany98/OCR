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


# ---------------------------------------------------------------------------
# SQLite compatibility shims.
#
# The app schema is PostgreSQL-only: ``document_chunks.embedding`` is a
# pgvector ``VECTOR(768)`` column and ``document_chunks.tsv`` is a
# ``GENERATED ALWAYS AS (to_tsvector('simple', ...))`` stored column.
# CI runs the suite against a real ``pgvector/pgvector:pg16`` service, so
# both are fine there. But a developer running ``pytest`` locally without
# a Postgres container gets ~180 cascading failures: ``Base.metadata.create_all``
# blows up with ``sqlite3.OperationalError: unrecognized token: ":"`` before
# any test body runs, and every fixture that needs ``db_session`` inherits
# the error.
#
# The shims below register ``@compiles`` overrides that translate the two
# Postgres-only constructs into SQLite-friendly equivalents *only when the
# target dialect is SQLite*. They have no effect on the Postgres CI run
# (the overrides are never consulted there), so the production DDL is
# untouched. The goal is "a local ``pytest`` without Postgres is green or
# skipped, not red".
# ---------------------------------------------------------------------------


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


def pytest_configure(config):
    """Register the ``requires_postgres`` marker.

    Tests that genuinely need pgvector (real cosine search, the tsvector
    column, the re-embed pipeline against a live model) opt in with
    ``@pytest.mark.requires_postgres``. The auto-skip below keeps the
    local SQLite run meaningful.
    """
    config.addinivalue_line(
        "markers",
        "requires_postgres: test needs a live PostgreSQL+pgvector DB "
        "(skipped automatically when DATABASE_URL is not postgres)",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-tag contract tests and apply the environment auto-skips."""
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

    # C2: skip tests that need a real PostgreSQL+pgvector backend when
    # the configured DATABASE_URL is not postgres. CI always sets a
    # postgres URL, so this only trims the local SQLite run.
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        skip_pg = pytest.mark.skip(
            reason="requires PostgreSQL+pgvector (set DATABASE_URL to a postgres URL to run)"
        )
        for item in items:
            if item.get_closest_marker("requires_postgres"):
                item.add_marker(skip_pg)


def _register_sqlite_schema_overrides() -> None:
    """Register ``@compiles`` overrides for the Postgres-only schema bits.

    Idempotent and import-safe: called once at conftest import time. If
    pgvector is not installed (e.g. the CPU-only local venv), the
    ``Vector`` fallback in ``app.models.document`` already renders as JSON
    and there is nothing for us to override for VECTOR.
    """
    from sqlalchemy import Computed
    from sqlalchemy.dialects.sqlite.base import SQLiteDDLCompiler
    from sqlalchemy.ext.compiler import compiles

    try:
        from pgvector.sqlalchemy import VECTOR
    except Exception:  # pragma: no cover - local env may use the JSON fallback
        VECTOR = None

    if VECTOR is not None:
        # 1. VECTOR(N) -> BLOB on SQLite. Postgres keeps using the native type.
        @compiles(VECTOR, "sqlite")
        def _compile_vector_sqlite(type_, compiler, **kw):  # noqa: ANN001
            return "BLOB"

    # 2. Generated columns (``Computed``) -> drop the generation clause on
    #    SQLite. The only ``Computed`` column in the schema is
    #    ``document_chunks.tsv``, whose expression is
    #    ``to_tsvector('simple', COALESCE(chunk_text, ''::text))`` — Postgres-
    #    only (uses ``to_tsvector`` and the ``::`` cast syntax). SQLite has
    #    generated columns too, but the expression is invalid there, so
    #    compiling the ``Computed`` to an empty string makes the column a
    #    plain ``TEXT`` on SQLite. The column is never read by SQLite-backed
    #    tests; the real full-text path is exercised by the
    #    ``requires_postgres`` tests in CI.
    @compiles(Computed, "sqlite")
    def _drop_computed_sqlite(expr, compiler, **kw):  # noqa: ANN001
        return ""

    # SQLAlchemy renders Computed through SQLiteDDLCompiler.visit_computed_column
    # in CREATE TABLE DDL, bypassing the generic @compiles hook above.
    if not getattr(SQLiteDDLCompiler.visit_computed_column, "_docuintel_patched", False):

        def _visit_computed_column_sqlite(self, generated, **kw):  # noqa: ANN001
            return ""

        _visit_computed_column_sqlite._docuintel_patched = True  # type: ignore[attr-defined]
        SQLiteDDLCompiler.visit_computed_column = _visit_computed_column_sqlite


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


# Register the SQLite schema overrides once the function is defined above.
_register_sqlite_schema_overrides()
