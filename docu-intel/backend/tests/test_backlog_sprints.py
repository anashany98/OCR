from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

settings.database_url = "sqlite+pysqlite:///:memory:"

from app.api.router import api_router
from app.core.security import hash_password
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    ApiClientBudgetScope,
    BudgetScope,
    Document,
    DocumentChunk,
    ExtractionJob,
    IntegrationClient,
    User,
)
from app.services.integration_security import hash_integration_api_key


def _test_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(api_router)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def _integration_headers(api_key: str = "secret-key", technician_id: str = "tech-1") -> dict[str, str]:
    return {"X-DocuIntel-API-Key": api_key, "X-Technician-Id": technician_id}


def test_auth_cookie_is_secure_in_production_and_samesite_lax(monkeypatch):
    client, sessions = _test_client()
    monkeypatch.setattr(settings, "environment", "production")
    with sessions() as db:
        db.add(
            User(
                email="admin@local",
                name="Admin",
                password_hash=hash_password("correct-password"),
                role="admin",
                is_active=True,
            )
        )
        db.commit()

    response = client.post("/auth/login", json={"email": "admin@local", "password": "correct-password"})

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "httponly" in cookie


def test_integration_upload_rejects_budget_code_without_client_permission(tmp_path, monkeypatch):
    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "integration_enqueue_uploads", False)
    with sessions() as db:
        client_model = IntegrationClient(
            name="external-tool",
            api_key_hash=hash_integration_api_key("secret-key"),
            scopes_json=["read", "upload"],
            is_active=True,
        )
        scope_a = BudgetScope(budget_code="A-100", display_name="Scope A")
        scope_b = BudgetScope(budget_code="B-200", display_name="Scope B")
        db.add_all([client_model, scope_a, scope_b])
        db.flush()
        db.add(ApiClientBudgetScope(api_client_id=client_model.id, budget_scope_id=scope_a.id, can_query=True))
        db.commit()

    response = client.post(
        "/integrations/v1/documents/upload",
        headers=_integration_headers(),
        data={"budget_code": "B-200"},
        files={"file": ("nota.txt", b"Referencia ABC123", "text/plain")},
    )

    assert response.status_code == 403
    with sessions() as db:
        assert db.scalar(select(Document).where(Document.original_filename == "nota.txt")) is None


def test_register_upload_rejects_files_over_configured_limit(tmp_path, monkeypatch):
    from app.services.document_service import register_upload

    sessions = _test_client()[1]
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)

    with sessions() as db:
        with pytest.raises(ValueError, match="max_upload_size"):
            register_upload(
                db,
                filename="grande.txt",
                stream=_BytesStream(b"x"),
                user=None,
                enqueue=False,
            )


def test_file_security_validates_magic_signatures_and_blocks_office_docs(tmp_path, monkeypatch):
    from app.services.file_security import inspect_file_for_ingestion

    monkeypatch.setattr(settings, "allowed_file_extensions", [".pdf", ".png", ".jpg", ".xlsx", ".docx"])
    fake_pdf = tmp_path / "factura.pdf"
    fake_pdf.write_bytes(b"not a pdf")
    docx = tmp_path / "contrato.docx"
    docx.write_bytes(b"PK\x03\x04fake office document")

    assert inspect_file_for_ingestion(fake_pdf).reason == "invalid_pdf_signature"
    assert inspect_file_for_ingestion(docx).reason == "office_document_blocked"


def test_parser_limits_reject_huge_images_and_excel(monkeypatch, tmp_path):
    from PIL import Image

    from app.parsers.excel import parse_excel
    from app.parsers.image import parse_image

    image_path = tmp_path / "huge.png"
    Image.new("RGB", (20, 20), color="white").save(image_path)
    monkeypatch.setattr(settings, "max_image_megapixels", 0.0001)
    with pytest.raises(ValueError, match="max_image_megapixels"):
        parse_image(image_path, ocr_engine=None)  # type: ignore[arg-type]

    import pandas as pd

    excel_path = tmp_path / "huge.xlsx"
    pd.DataFrame({"a": range(5)}).to_excel(excel_path, index=False)
    monkeypatch.setattr(settings, "max_excel_rows", 3)
    with pytest.raises(ValueError, match="max_excel_rows"):
        parse_excel(excel_path)


def test_watcher_reingests_modified_source_path_when_hash_changes(tmp_path, monkeypatch):
    from app.ingestion.watcher import ingest_path_if_ready

    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 0)

    source = tmp_path / "input" / "nota.txt"
    source.parent.mkdir()
    source.write_text("version uno", encoding="utf-8")

    with sessions() as db:
        first = ingest_path_if_ready(db, source, enqueue=False)
        source.write_text("version dos", encoding="utf-8")
        second = ingest_path_if_ready(db, source, enqueue=False)
        documents = list(db.scalars(select(Document).where(Document.source_path == str(source))).all())

    assert first["document_id"] != second["document_id"]
    assert second["status"] == "pending"
    assert len(documents) == 2


def test_pgvector_store_requires_budget_scope_filter():
    from app.services.vector_store import PgvectorStore

    with pytest.raises(ValueError, match="budget_scope_id"):
        PgvectorStore().search(db=None, query_embedding=[0.1] * 1024, limit=10, filters={})  # type: ignore[arg-type]


def test_embedding_fallback_metadata_is_persisted(monkeypatch):
    from app.services import document_service

    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: True)
    monkeypatch.setattr(document_service, "embed_many_with_metadata", lambda texts: [([0.1] * 1024, "local_hash", True) for _ in texts])

    chunks = document_service.prepare_document_chunks(7, [(1, "Referencia ABC123 " * 80)])

    assert chunks
    assert all(chunk.embedding_provider_used == "local_hash" for chunk in chunks)
    assert all(chunk.embedding_fallback is True for chunk in chunks)
    assert all(chunk.needs_reembedding is True for chunk in chunks)


def test_admin_health_includes_ai_and_embedding_checks(monkeypatch):
    client, sessions = _test_client()
    with sessions() as db:
        db.add(
            User(
                email="admin@local",
                name="Admin",
                password_hash=hash_password("secret"),
                role="admin",
                is_active=True,
            )
        )
        db.flush()
        from app.core.security import create_access_token

        token = create_access_token("1")
        db.commit()

    response = client.get("/admin/system/health", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    checks = response.json()["checks"]
    assert "ai_llm" in checks
    assert "embeddings" in checks


def test_local_compose_splits_worker_queues():
    compose = Path(__file__).resolve().parents[1].parent / "docker-compose.yml"
    content = compose.read_text(encoding="utf-8")

    assert "worker-fast:" in content
    assert "worker-heavy:" in content
    assert "worker-maintenance:" in content
    assert "-Q ocr_heavy" in content
    assert "OCR_WORKER_CONCURRENCY:-1" in content


def test_internal_ai_context_redacts_amounts_without_price_permission():
    from app.ai.agent import ContextItem, redact_context_items_for_scope
    from app.services.tenant_access import AccessScope

    scope = AccessScope(principal_type="user", principal_id="2", can_view_prices=False)
    items = [
        ContextItem(
            title="presupuesto.pdf",
            summary="Total 1.245,60 € y margen 18%",
            excerpt="Precio unitario 22,50 €",
        )
    ]

    redacted = redact_context_items_for_scope(items, scope)

    rendered = f"{redacted[0].summary} {redacted[0].excerpt}"
    assert "1.245,60" not in rendered
    assert "22,50" not in rendered
    assert "18%" not in rendered
    assert "[IMPORTE OCULTO]" in rendered


class _BytesStream:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._read = False

    def read(self, _: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._payload
