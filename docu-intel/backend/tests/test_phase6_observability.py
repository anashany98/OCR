# Phase 6 observability tests
from __future__ import annotations

import os
from pathlib import Path as _Path
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
settings.database_url = "sqlite+pysqlite:///:memory:"

from app.api.router import api_router
from app.core.security import create_access_token, hash_password
from app.database.base import Base
from app.database.session import get_db
from app.models import Document, DocumentPage, User
from app.services import metrics as metrics_module
from app.services.metrics import register_metrics_endpoint
from app.services.metrics import get_metrics


def _test_client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(api_router)
    def override_get_db():
        db = sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_get_db
    register_metrics_endpoint(app)
    from app.middleware.performance_monitor import PerformanceMonitorMiddleware
    app.add_middleware(PerformanceMonitorMiddleware)
    return TestClient(app), sessions


def _seed_admin(db):
    user = User(email="admin@local", name="Admin", password_hash=hash_password("secret"), role="admin", is_active=True)
    db.add(user); db.flush(); db.commit()
    return create_access_token(str(user.id))


def _seed_document(db, filename="scan.pdf", status="pending", quality="pending"):
    doc = Document(original_filename=filename, stored_filename=f"aa/{filename}",
                   source_path=f"/data/input/{filename}", file_hash="a"*64,
                   mime_type="application/pdf", extension=".pdf", file_size=10,
                   document_type="plano", status=status, quality_status=quality)
    db.add(doc); db.flush()
    return doc


def _search_total_count() -> float:
    """Sum of all ``docuintel_search_duration_seconds_count``
    observations across every label set.

    ``prometheus_client`` exposes the count of observations
    through the public ``REGISTRY.get_sample_value`` API; we use
    that instead of poking at private histogram internals.
    """
    from prometheus_client import REGISTRY

    total = 0.0
    for labels in _search_seen_labels():
        value = REGISTRY.get_sample_value(
            "docuintel_search_duration_seconds_count", labels
        )
        if value is not None:
            total += value
    return total


def _search_seen_labels() -> list[dict[str, str]]:
    """Read the per-label-set that the search histogram has
    recorded so far. We iterate the child objects because the
    public API does not list "every label set that exists" — it
    only takes a specific label set as input.
    """
    from app.services.metrics import _registry

    seen: list[dict[str, str]] = []
    for child_key in _registry.SEARCH_DURATION._metrics.keys():
        # ``child_key`` is a tuple like ``("unknown",)``. The
        # public ``get_sample_value`` API takes a dict whose
        # keys match the label names.
        if not child_key:
            continue
        seen.append({"strategy": child_key[0]})
    return seen


def test_search_metrics_increment_on_search_text():
    from app.services.search_service import search_text
    sessions = _test_client()[1]
    with sessions() as db:
        doc = _seed_document(db, "one.txt", status="processed", quality="processed_ok")
        db.add(DocumentPage(document_id=doc.id, page_number=1, text="referencia ABC123 pedido confirmado"))
        db.commit()
        before = _search_total_count()
        search_text(db, "ABC123", limit=5)
        after = _search_total_count()
    assert after > before


def test_search_metrics_increment_on_empty_query():
    from app.services.search_service import search_text, search_semantic
    sessions = _test_client()[1]
    with sessions() as db:
        before = _search_total_count()
        search_text(db, "", limit=5)
        search_semantic(db, "", limit=5)
        after = _search_total_count()
    assert after >= before + 2


def test_system_health_includes_required_keys():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
    resp = client.get("/admin/system/health", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    for key in ["database", "redis", "disk_files", "disk_input", "watcher", "queues", "ai_llm", "embeddings"]:
        assert key in checks, f"missing {key}"
    assert checks["database"]["status"] == "ok"


def test_system_health_does_not_call_external_ai_by_default(monkeypatch):
    http_calls = []
    monkeypatch.setattr("httpx.Client.post", lambda *a, **kw: http_calls.append(kw) or (_ for _ in ()).throw(RuntimeError("blocked")))
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
    resp = client.get("/admin/system/health", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (200, 503)
    assert len(http_calls) == 0


def test_readiness_includes_required_keys():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
    resp = client.get("/admin/production/readiness", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    for key in ["database", "redis", "workers", "watcher", "files_dir", "input_dir", "backups"]:
        assert any(c["key"] == key for c in data["checks"]), f"missing {key}"


def test_metrics_endpoint_exposes_counters():
    """Verify the prometheus_client exposition format includes the
    full set of metrics we expect. The metric names have changed
    slightly from the hand-written format (e.g.
    ``docuintel_ocr_duration_seconds`` is now a ``Histogram`` so
    the ``_total`` suffix is added by the library, and
    ``search`` is recorded as a labelled histogram rather than a
    pair of sum/count counters)."""
    client, sessions = _test_client()
    with sessions() as db:
        _seed_admin(db)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    for name in [
        "docuintel_ocr_duration_seconds",  # Histogram (no _total)
        "docuintel_search_duration_seconds",
        "docuintel_cache_hits_total",
        "docuintel_documents_processed_total",
        "docuintel_documents_failed_total",
        "docuintel_embedding_fallbacks_total",
        "docuintel_watcher_errors_total",
    ]:
        assert name in body, f"missing {name} in /metrics"


def test_readiness_has_top_level_status():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
    resp = client.get("/admin/production/readiness", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_performance_middleware_adds_response_time_header():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
    resp = client.get("/admin/production/readiness", headers={"Authorization": f"Bearer {token}"})
    assert "x-response-time" in resp.headers


def test_search_semantic_metrics_on_cache_hit(monkeypatch):
    """Cache hit on the semantic path: the metric must still
    record the call (otherwise cache hits would silently
    disappear from the latency histogram)."""
    from app.services.search_service import search_semantic
    from app.services.cache import cache_service
    sessions = _test_client()[1]
    fake_result = {"document_id": 1, "original_filename": "x", "document_type": "t", "status": "p",
                   "page_number": 1, "block_id": None, "score": 0.9, "excerpt": "...",
                   "ocr_confidence": None, "source_type": "semantic_chunk"}
    monkeypatch.setattr(cache_service, "get", lambda key: [fake_result])
    with sessions() as db:
        _seed_document(db, "x.pdf", status="processed", quality="processed_ok")
        db.commit()
        before = _search_total_count()
        search_semantic(db, "test", limit=5)
        after = _search_total_count()
    assert after > before
