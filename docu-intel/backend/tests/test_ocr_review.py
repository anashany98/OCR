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
from app.models import AuditLog, Document, DocumentBlock, DocumentChunk, DocumentPage, ExtractionJob, User
from app.services import document_service


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


def test_admin_ocr_review_excludes_decorative_or_native_pages():
    client, sessions = _test_client()
    with sessions() as db:
        token = _seed_admin(db)
        document = _seed_document_with_pages(db)
        db.add_all(
            [
                DocumentPage(
                    document_id=document.id,
                    page_number=3,
                    text="Logotipo del proveedor",
                    image_path="pages/logo.png",
                    ocr_confidence=0.10,
                    ocr_content_kind="decorative",
                ),
                DocumentPage(
                    document_id=document.id,
                    page_number=4,
                    text="Texto de un PDF digital",
                    ocr_confidence=0.10,
                    ocr_content_kind="native_text",
                ),
            ]
        )
        db.commit()

    response = client.get("/admin/ocr-review?max_confidence=0.70", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert [item["page_number"] for item in response.json()] == [1]


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


def test_document_page_image_endpoint_serves_jpeg_with_correct_content_type(tmp_path: Path, monkeypatch):
    """OPS-1: when the page preview was rendered as JPEG, the
    endpoint must advertise ``image/jpeg`` and not
    ``image/png`` (which was the historical bug — the bytes
    were JPEG but the filename was ``.png`` so the browser
    inferred the wrong MIME).
    """
    from sqlalchemy import select

    from app.models import DocumentPage

    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    page_dir = tmp_path / "pages"
    page_dir.mkdir(parents=True)
    # Fake JPEG SOI marker so the helper at least has a
    # consistent on-disk format. The test only cares that the
    # route advertises ``image/jpeg`` when the suffix is
    # ``.jpg``.
    (page_dir / "page-1.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)

    with sessions() as db:
        token = _seed_admin(db)
        document = _seed_document_with_pages(db)
        # The seed helper hard-codes ``image_path`` to
        # ``pages/page-1.png``; switch it to ``.jpg`` so the
        # endpoint sees a JPEG-named file and must serve it
        # with the matching Content-Type.
        page_one = db.scalar(
            select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1)
        )
        page_one.image_path = "pages/page-1.jpg"
        db.commit()

    response = client.get(f"/documents/{document.id}/pages/1/image", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    # The endpoint must serve the bytes with the matching
    # Content-Type so the browser actually renders the
    # preview (some refuse to display ``image/png`` bytes
    # served as ``image/jpeg`` and vice versa).
    assert response.headers["content-type"] == "image/jpeg", (
        "OPS-1: pages rendered as JPEG must be served with "
        "Content-Type: image/jpeg, not inferred from a stale "
        ".png suffix"
    )


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


def test_admin_page_reprocess_enqueues_page_specific_ocr_job(monkeypatch):
    client, sessions = _test_client()
    monkeypatch.setattr("app.workers.tasks.process_document_task.apply_async", lambda *args, **kwargs: None)
    with sessions() as db:
        token = _seed_admin(db)
        document = _seed_document_with_pages(db)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1))

    response = client.post(f"/admin/quality/pages/{page.id}/reprocess-ocr", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["job_type"] == "reprocess:ocr_page:1"
    with sessions() as db:
        refreshed_page = db.get(DocumentPage, page.id)
        job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == document.id))
        assert refreshed_page.page_status == "queued"
        assert job.job_type == "reprocess:ocr_page:1"


def test_process_page_specific_ocr_job_replaces_only_selected_page(monkeypatch, tmp_path: Path):
    from app.ocr.paddle import OCRBlock, OCRResult
    from app.services import document_service
    from app.services import document_processing_core

    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    page_dir = tmp_path / "pages"
    page_dir.mkdir(parents=True)
    (page_dir / "page-1.png").write_bytes(b"fake-png")
    (page_dir / "page-2.png").write_bytes(b"fake-png")

    class FakeOcrEngine:
        def extract(self, image_path: Path) -> OCRResult:
            assert image_path == page_dir / "page-1.png"
            return OCRResult(
                text="Texto OCR corregido Referencia ABC999",
                confidence=0.93,
                blocks=[OCRBlock(text="Texto OCR corregido", confidence=0.93, bbox=(1.0, 2.0, 3.0, 4.0))],
                engine="paddleocr",
            )

    monkeypatch.setattr(document_service, "get_ocr_engine_class", lambda: FakeOcrEngine)
    monkeypatch.setattr(document_processing_core, "_get_effective_ocr_engine_class", lambda: FakeOcrEngine)
    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: False)

    with sessions() as db:
        _seed_admin(db)
        document = _seed_document_with_pages(db)
        page_one = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1))
        page_two = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 2))
        db.add_all(
            [
                DocumentBlock(document_id=document.id, page_id=page_one.id, page_number=1, text="bloque viejo", confidence=0.61),
                DocumentBlock(document_id=document.id, page_id=page_two.id, page_number=2, text="bloque estable", confidence=0.91),
                DocumentChunk(document_id=document.id, page_number=1, chunk_text="chunk viejo", token_count=2),
            ]
        )
        job = document_service.reprocess_document_page(db, page=page_one, user=None, enqueue=False)
        document_service.process_document(db, document_id=document.id, job_id=job.id)

        refreshed_one = db.get(DocumentPage, page_one.id)
        refreshed_two = db.get(DocumentPage, page_two.id)
        blocks = list(db.scalars(select(DocumentBlock).where(DocumentBlock.document_id == document.id).order_by(DocumentBlock.page_number.asc())).all())
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.page_number.asc())).all())
        refreshed_job = db.get(ExtractionJob, job.id)

    assert refreshed_one.text == "Texto OCR corregido Referencia ABC999"
    assert refreshed_one.ocr_confidence == 0.93
    assert refreshed_one.page_status == "processed"
    assert refreshed_one.attempts == 1
    assert refreshed_one.processing_time_ms is not None
    assert refreshed_two.text == "Texto OCR fiable"
    assert [(block.page_number, block.text) for block in blocks] == [(1, "Texto OCR corregido"), (2, "bloque estable")]
    assert any(chunk.page_number == 1 and "ABC999" in chunk.chunk_text for chunk in chunks)
    assert any(chunk.page_number == 2 and "Texto OCR fiable" in chunk.chunk_text for chunk in chunks)
    assert refreshed_job.status == "processed"


def test_page_specific_ocr_job_routes_to_heavy_queue(monkeypatch):
    calls: list[dict] = []
    client, sessions = _test_client()
    monkeypatch.setattr("app.workers.tasks.process_document_task.apply_async", lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}))
    with sessions() as db:
        _seed_admin(db)
        document = _seed_document_with_pages(db)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1))
        job = document_service.reprocess_document_page(db, page=page, user=None, enqueue=True)

    assert job.job_type == "reprocess:ocr_page:1"
    assert calls == [{"args": (), "kwargs": {"args": (document.id, job.id), "queue": "ocr_heavy"}}]


def test_page_specific_ocr_missing_image_path_does_not_call_full_parse(monkeypatch):
    from app.services import document_service
    from app.services import document_processing_core

    client, sessions = _test_client()
    monkeypatch.setattr(document_service, "_process_full_parse", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full parse should not run")))
    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: False)

    with sessions() as db:
        _seed_admin(db)
        document = _seed_document_with_pages(db)
        page_one = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1))
        page_one.image_path = None
        job = document_service.reprocess_document_page(db, page=page_one, user=None, enqueue=False)
        document_service.process_document(db, document_id=document.id, job_id=job.id)

        refreshed_document = db.get(Document, document.id)
        refreshed_page = db.get(DocumentPage, page_one.id)
        refreshed_job = db.get(ExtractionJob, job.id)

    assert refreshed_document.status == "needs_review"
    assert refreshed_page.page_status == "failed"
    assert "no image preview" in refreshed_page.error_message
    assert refreshed_job.status == "processed"


def test_page_specific_ocr_outside_files_dir_fails_without_full_parse(monkeypatch, tmp_path: Path):
    from app.services import document_service

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fake-png")
    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(document_service, "_process_full_parse", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full parse should not run")))
    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: False)

    with sessions() as db:
        _seed_admin(db)
        document = _seed_document_with_pages(db)
        page_one = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1))
        page_one.image_path = str(outside)
        job = document_service.reprocess_document_page(db, page=page_one, user=None, enqueue=False)
        document_service.process_document(db, document_id=document.id, job_id=job.id)

        refreshed_document = db.get(Document, document.id)
        refreshed_page = db.get(DocumentPage, page_one.id)
        refreshed_job = db.get(ExtractionJob, job.id)

    assert refreshed_document.status == "needs_review"
    assert refreshed_page.page_status == "failed"
    assert refreshed_page.error_message == "Stored page image is outside files directory"
    assert refreshed_job.status == "processed"


def test_failed_page_specific_ocr_marks_page_failed_without_failing_document(monkeypatch, tmp_path: Path):
    from app.services import document_service
    from app.services import document_processing_core

    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    page_dir = tmp_path / "pages"
    page_dir.mkdir(parents=True)
    (page_dir / "page-1.png").write_bytes(b"fake-png")

    class FailingOcrEngine:
        def extract(self, image_path: Path):
            raise RuntimeError("ocr timeout")

    monkeypatch.setattr(document_service, "get_ocr_engine_class", lambda: FailingOcrEngine)
    monkeypatch.setattr(document_processing_core, "_get_effective_ocr_engine_class", lambda: FailingOcrEngine)
    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: False)

    with sessions() as db:
        _seed_admin(db)
        document = _seed_document_with_pages(db)
        page_one = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).where(DocumentPage.page_number == 1))
        job = document_service.reprocess_document_page(db, page=page_one, user=None, enqueue=False)
        document_service.process_document(db, document_id=document.id, job_id=job.id)

        refreshed_document = db.get(Document, document.id)
        refreshed_page = db.get(DocumentPage, page_one.id)
        refreshed_job = db.get(ExtractionJob, job.id)

    assert refreshed_document.status == "needs_review"
    assert refreshed_document.quality_status == "technical_failure"
    assert refreshed_page.page_status == "failed"
    assert refreshed_page.error_message == "ocr timeout"
    assert refreshed_page.attempts == 1
    assert refreshed_job.status == "processed"
