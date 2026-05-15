from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

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
from app.models import AuditLog, Document, DocumentPage, ExtractionJob, User


def _test_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(api_router)

    def override_get_db() -> Generator[Session, None, None]:
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), sessions


def _seed_admin(db: Session) -> str:
    user = User(email="admin@local", name="Admin", password_hash=hash_password("secret"), role="admin", is_active=True)
    db.add(user)
    db.flush()
    return create_access_token(str(user.id))


def _seed_document_with_pages(db: Session) -> Document:
    document = Document(
        original_filename="plano_baja_confianza.png",
        stored_filename="aa/plano_baja_confianza.png",
        source_path="/data/input/planos/plano_baja_confianza.png",
        file_hash="a" * 64,
        mime_type="image/png",
        extension=".png",
        file_size=1200,
        document_type="plano",
        status="needs_review",
        confidence=0.61,
        page_count=2,
    )
    db.add(document)
    db.flush()
    db.add_all(
        [
            DocumentPage(
                document_id=document.id,
                page_number=1,
                text="Texto OCR dudoso Total 1.245,60 euros referencia ABC123",
                image_path="pages/page-1.png",
                ocr_confidence=0.61,
            ),
            DocumentPage(
                document_id=document.id,
                page_number=2,
                text="Texto OCR fiable",
                image_path="pages/page-2.png",
                ocr_confidence=0.91,
            ),
        ]
    )
    db.commit()
    return document


def test_admin_ocr_review_lists_pages_below_confidence_threshold():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
        document = _seed_document_with_pages(db)

    response = client.get("/admin/ocr-review?max_confidence=0.70", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["document_id"] == document.id
    assert payload[0]["original_filename"] == "plano_baja_confianza.png"
    assert payload[0]["page_number"] == 1
    assert payload[0]["ocr_confidence"] == 0.61
    assert payload[0]["review_status"] == "pending"
    assert payload[0]["text"] == "Texto OCR dudoso Total 1.245,60 euros referencia ABC123"
    assert payload[0]["preview_url"] == f"/documents/{document.id}/pages/1/image"


def test_document_page_image_endpoint_serves_page_preview_from_files_dir(tmp_path: Path, monkeypatch):
    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    page_dir = tmp_path / "pages"
    page_dir.mkdir(parents=True)
    (page_dir / "page-1.png").write_bytes(b"fake-png")

    with sessions() as db:
        token = _seed_admin(db)
        document = _seed_document_with_pages(db)

    response = client.get(f"/documents/{document.id}/pages/1/image", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.content == b"fake-png"
    assert response.headers["content-type"] == "image/png"


def test_admin_can_approve_low_confidence_page_and_it_leaves_review_queue():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
        _seed_document_with_pages(db)
        page = db.scalar(select(DocumentPage).where(DocumentPage.page_number == 1))
        page_id = page.id

    response = client.patch(
        f"/admin/ocr-review/{page_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"review_status": "approved", "review_notes": "Texto validado manualmente"},
    )
    queue = client.get("/admin/ocr-review?max_confidence=0.70", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == "approved"
    assert payload["review_notes"] == "Texto validado manualmente"
    assert queue.status_code == 200
    assert queue.json() == []
    with sessions() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "ocr_review_page_updated"))
        assert audit is not None
        assert audit.details_json["review_status"] == "approved"


def test_admin_can_reject_low_confidence_page_and_it_remains_actionable():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
        _seed_document_with_pages(db)
        page = db.scalar(select(DocumentPage).where(DocumentPage.page_number == 1))
        page_id = page.id

    response = client.patch(
        f"/admin/ocr-review/{page_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"review_status": "rejected"},
    )
    queue = client.get("/admin/ocr-review?max_confidence=0.70", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"
    assert queue.status_code == 200
    assert queue.json()[0]["review_status"] == "rejected"


def test_document_reprocess_accepts_ocr_mode_for_review_panel(monkeypatch):
    client, sessions = _test_client()
    monkeypatch.setattr("app.workers.tasks.process_document_task.apply_async", lambda *args, **kwargs: None)
    with sessions() as db:
        token = _seed_admin(db)
        document = _seed_document_with_pages(db)

    response = client.post(f"/documents/{document.id}/reprocess?mode=ocr", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["job_type"] == "reprocess:ocr"
    with sessions() as db:
        job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == document.id))
        assert job.job_type == "reprocess:ocr"
