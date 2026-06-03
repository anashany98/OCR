from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

settings.database_url = "sqlite+pysqlite:///:memory:"

from app.database.base import Base
from app.models import Document, DocumentBlock, DocumentChunk, DocumentPage, ExtractionJob
from app.ocr.paddle import OCRBlock, OCRResult
from app.services import document_service


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _configure_pipeline(monkeypatch, tmp_path, *, create_embeddings: bool = False, needs_review: bool = False) -> tuple[Path, Path]:
    input_dir = tmp_path / "input"
    files_dir = tmp_path / "files"
    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", files_dir)
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")
    monkeypatch.setattr(settings, "allowed_file_extensions", [".txt", ".csv", ".xlsx", ".pdf", ".png", ".exe"])
    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: create_embeddings)
    monkeypatch.setattr(document_service, "persist_business_extraction", lambda *args, **kwargs: type("BusinessResult", (), {"needs_review": False})())
    monkeypatch.setattr(document_service, "persist_plan_extraction", lambda *args, **kwargs: type("PlanResult", (), {"needs_review": False})())
    monkeypatch.setattr(document_service, "evaluate_document_quality", lambda *args, **kwargs: type("QualityResult", (), {"needs_review": needs_review})())
    monkeypatch.setattr(document_service, "update_document_quality", lambda *args, **kwargs: None)
    monkeypatch.setattr(document_service, "_emit_document_webhooks", lambda *args, **kwargs: None)
    return input_dir, files_dir


def _register_and_process(db: Session, source: Path) -> tuple[Document, ExtractionJob]:
    document, job = document_service.register_existing_file(db, source=source, source_path=str(source), enqueue=False)
    assert job is not None
    document_service.process_document(db, document_id=document.id, job_id=job.id)
    processed = db.get(Document, document.id)
    processed_job = db.get(ExtractionJob, job.id)
    assert processed is not None
    assert processed_job is not None
    return processed, processed_job


def test_plain_text_document_pipeline_registers_pages_blocks_and_chunks(tmp_path, monkeypatch):
    input_dir, files_dir = _configure_pipeline(monkeypatch, tmp_path)
    source = input_dir / "pedidos" / "pedido-123.txt"
    source.parent.mkdir(parents=True)
    source.write_text(
        "Pedido P-123 para Hotel Demo. Fecha pedido: 14/05/2026. Referencia ABC123 con dos unidades procesadas correctamente.",
        encoding="utf-8",
    )
    sessions = _session_factory()
    with sessions() as db:
        document, job = document_service.register_existing_file(
            db,
            source=source,
            source_path=str(source),
            enqueue=False,
        )
        assert job is not None
        document_id = document.id
        job_id = job.id

        stored_path = files_dir / str(document.stored_filename)
        assert stored_path.is_file()
        assert stored_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

        document_service.process_document(db, document_id=document_id, job_id=job_id)

        processed = db.get(Document, document_id)
        processed_job = db.get(ExtractionJob, job_id)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document_id))
        block = db.scalar(select(DocumentBlock).where(DocumentBlock.document_id == document_id))
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all())

    assert processed is not None
    assert processed.status == "processed"
    assert processed.page_count == 1
    assert processed_job is not None
    assert processed_job.status == "processed"
    assert page is not None
    assert "Referencia ABC123" in (page.text or "")
    assert block is not None
    assert block.source_engine == "plain_text"
    assert chunks
    assert chunks[0].chunk_text.startswith("Pedido P-123")


def test_csv_and_excel_pipeline_extract_small_tables(tmp_path, monkeypatch):
    pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    import pandas as pd

    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    csv_source = input_dir / "ventas.csv"
    xlsx_source = input_dir / "ventas.xlsx"
    input_dir.mkdir(parents=True)
    csv_source.write_text("cliente,importe\nHotel Demo,42\n", encoding="utf-8")
    pd.DataFrame([{"cliente": "Hotel Demo", "importe": 42}]).to_excel(xlsx_source, index=False, header=False)

    sessions = _session_factory()
    with sessions() as db:
        csv_doc, csv_job = _register_and_process(db, csv_source)
        xlsx_doc, xlsx_job = _register_and_process(db, xlsx_source)
        csv_block = db.scalar(select(DocumentBlock).where(DocumentBlock.document_id == csv_doc.id))
        xlsx_block = db.scalar(select(DocumentBlock).where(DocumentBlock.document_id == xlsx_doc.id))

    assert csv_doc.status == "processed"
    assert csv_job.status == "processed"
    assert "Hotel Demo" in csv_block.text
    assert csv_block.source_engine == "plain_text"
    assert xlsx_doc.status == "processed"
    assert xlsx_job.status == "processed"
    assert "Hotel Demo | 42" in xlsx_block.text
    assert xlsx_block.source_engine == "pandas"


def test_digital_pdf_pipeline_uses_pymupdf_without_ocr(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    source = input_dir / "digital.pdf"
    source.parent.mkdir(parents=True)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Factura digital con texto suficiente para evitar OCR externo en pruebas")
    pdf.save(source)
    pdf.close()

    sessions = _session_factory()
    with sessions() as db:
        document, job = _register_and_process(db, source)
        block = db.scalar(select(DocumentBlock).where(DocumentBlock.document_id == document.id))

    assert document.status == "processed"
    assert job.status == "processed"
    assert document.page_count == 1
    assert block.source_engine == "pymupdf"


def test_image_pipeline_uses_mocked_ocr_for_tiny_png(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    source = input_dir / "ocr.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (1, 1), "white").save(source)

    class FakePaddleOCREngine:
        def extract(self, image_path: Path) -> OCRResult:
            return OCRResult(
                text="OCR simulado Hotel Demo",
                confidence=0.98,
                blocks=[OCRBlock(text="OCR simulado Hotel Demo", confidence=0.98, bbox=(0.0, 0.0, 1.0, 1.0))],
            )

    monkeypatch.setattr(document_service, "PaddleOCREngine", FakePaddleOCREngine)

    sessions = _session_factory()
    with sessions() as db:
        document, job = _register_and_process(db, source)
        block = db.scalar(select(DocumentBlock).where(DocumentBlock.document_id == document.id))

    assert document.status == "processed"
    assert job.status == "processed"
    assert block.text == "OCR simulado Hotel Demo"
    assert block.source_engine == "paddleocr"


def test_register_upload_matches_register_existing_file_for_same_hash(tmp_path, monkeypatch):
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    source = input_dir / "upload-source.txt"
    source.parent.mkdir(parents=True)
    payload = b"Documento subido y escaneado con el mismo contenido"
    source.write_bytes(payload)

    sessions = _session_factory()
    with sessions() as db:
        existing_doc, existing_job = document_service.register_existing_file(db, source=source, source_path=str(source), enqueue=False)
        assert existing_job is not None
        document_service.process_document(db, document_id=existing_doc.id, job_id=existing_job.id)
        upload_doc, upload_job = document_service.register_upload(
            db,
            filename="upload-source.txt",
            stream=BytesIO(payload),
            user=None,
            source_path=str(input_dir / "uploads" / "upload-source.txt"),
            enqueue=False,
        )

    assert upload_job is None
    assert upload_doc.id == existing_doc.id
    assert upload_doc.file_hash == existing_doc.file_hash


def test_sha256_dedup_scenarios_and_statuses(tmp_path, monkeypatch):
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path, needs_review=True)
    first = input_dir / "a" / "same.txt"
    second = input_dir / "b" / "same.txt"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("Documento que queda en revision por calidad", encoding="utf-8")
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")

    sessions = _session_factory()
    with sessions() as db:
        review_doc, review_job = _register_and_process(db, first)
        duplicate_doc, duplicate_job = document_service.register_existing_file(db, source=second, source_path=str(second), enqueue=False)
        first.write_text("Documento cambiado en la misma ruta con hash nuevo", encoding="utf-8")
        changed_doc, changed_job = document_service.register_existing_file(db, source=first, source_path=str(first), enqueue=False)

    assert review_doc.status == "needs_review"
    assert review_job.status == "processed"
    assert duplicate_doc.id == review_doc.id
    assert duplicate_job is None
    assert changed_doc.id != review_doc.id
    assert changed_doc.status == "pending"
    assert changed_job is not None
    assert changed_job.status == "pending"


def test_failed_document_hash_can_be_registered_again_for_recovery(tmp_path, monkeypatch):
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    first = input_dir / "failed" / "same.txt"
    second = input_dir / "retry" / "same.txt"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("Contenido que fallara durante parseo", encoding="utf-8")
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(document_service, "parse_document", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parse boom")))

    sessions = _session_factory()
    with sessions() as db:
        failed_doc, failed_job = document_service.register_existing_file(db, source=first, source_path=str(first), enqueue=False)
        with pytest.raises(RuntimeError, match="parse boom"):
            document_service.process_document(db, document_id=failed_doc.id, job_id=failed_job.id)
        retry_doc, retry_job = document_service.register_existing_file(db, source=second, source_path=str(second), enqueue=False)
        failed_doc = db.get(Document, failed_doc.id)
        failed_job = db.get(ExtractionJob, failed_job.id)

    assert failed_doc.status == "failed"
    assert failed_job.status == "failed"
    assert retry_doc.id != failed_doc.id
    assert retry_doc.status == "pending"
    assert retry_job is not None
    assert retry_job.status == "pending"


def test_reprocess_regenerates_chunks(tmp_path, monkeypatch):
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    source = input_dir / "reprocess.txt"
    source.parent.mkdir(parents=True)
    source.write_text("Texto original para chunk inicial", encoding="utf-8")

    sessions = _session_factory()
    with sessions() as db:
        document, _ = _register_and_process(db, source)
        original_chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all())
        stored_path = settings.files_dir / document.stored_filename
        stored_path.write_text("Texto reprocesado con contenido nuevo", encoding="utf-8")
        reprocess_job = document_service.reprocess_document(db, document=document, enqueue=False)
        document_service.process_document(db, document_id=document.id, job_id=reprocess_job.id)
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all())
        document = db.get(Document, document.id)

    assert document.status == "processed"
    assert chunks
    assert len(chunks) == len(original_chunks)
    assert all("Texto original" not in chunk.chunk_text for chunk in chunks)
    assert chunks[0].chunk_text.startswith("Texto reprocesado")


def test_embedding_provider_failure_falls_back_to_hash_without_blocking(tmp_path, monkeypatch):
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path, create_embeddings=True)
    monkeypatch.setattr(settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(settings, "embedding_base_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "embedding_fallback_to_hash", True)
    monkeypatch.setattr(settings, "embedding_dimensions", 1024)
    source = input_dir / "embeddings.txt"
    source.parent.mkdir(parents=True)
    source.write_text("Texto con embeddings que deben caer a hash local", encoding="utf-8")

    sessions = _session_factory()
    with sessions() as db:
        document, job = _register_and_process(db, source)
        chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document.id))

    assert document.status == "processed"
    assert job.status == "processed"
    assert chunk.embedding is not None
    assert len(chunk.embedding) > 0
    assert chunk.embedding_provider_used == "openai_compatible"


def test_invalid_file_is_quarantined_without_job(tmp_path, monkeypatch):
    input_dir, _ = _configure_pipeline(monkeypatch, tmp_path)
    source = input_dir / "bad.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"MZ executable pretending to be pdf")

    sessions = _session_factory()
    with sessions() as db:
        document, job = document_service.register_existing_file(db, source=source, source_path=str(source), enqueue=False)

    assert job is None
    assert document.status == "needs_review"
    assert document.quality_status == "needs_human_review"
    assert any(flag.startswith("security:") for flag in document.quality_flags_json)
    assert "quarantined" in document.error_message.lower()
