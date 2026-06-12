"""Smoke: app loads, all routes registered, ocr-flow routes present."""
from app.main import app
from app.api.routes.ocr_flow import router


def test_flow_router_has_three_routes():
    paths = sorted({r.path for r in router.routes})
    assert "/admin/ocr-flow/live" in paths
    assert "/admin/ocr-flow/stream" in paths
    assert "/documents/{document_id}/flow" in paths


def test_app_includes_flow_routes():
    registered = {r.path for r in app.routes if hasattr(r, "path")}
    # FastAPI's ``app.routes`` includes the literal paths defined on
    # each ``APIRouter``. The ``include_router`` call does not
    # mutate the paths on the sub-router.
    assert any(p.endswith("/admin/ocr-flow/live") for p in registered)
    assert any(p.endswith("/admin/ocr-flow/stream") for p in registered)
    assert any(p.endswith("/documents/{document_id}/flow") for p in registered)
