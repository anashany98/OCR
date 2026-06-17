"""Tests for the OCR flow timeline assembler."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.document import Document, DocumentPage, ExtractionJob
from app.models.ocr_cascade import OcrCascadeAttempt
from app.models.operations import IngestionEvent
from app.services.ocr_flow_timeline import build_document_flow


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_build_document_flow_merges_jobs_and_events_and_pages_and_cascade():
    s = _make_session()
    doc = Document(
        id=1,
        original_filename="factura.pdf",
        file_hash="x" * 64,
        status="processed",
    )
    s.add(doc)
    s.flush()
    s.add_all(
        [
            ExtractionJob(
                id=10,
                document_id=1,
                job_type="extract",
                status="finished",
                started_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
            ),
            IngestionEvent(
                id=100,
                event_type="watcher.detected",
                document_id=1,
                created_at=datetime(2026, 1, 1, 9, 59, tzinfo=timezone.utc),
            ),
            IngestionEvent(
                id=101,
                event_type="ingestion.committed",
                document_id=1,
                created_at=datetime(2026, 1, 1, 10, 0, 1, tzinfo=timezone.utc),
            ),
            DocumentPage(
                id=1000,
                document_id=1,
                page_number=1,
                ocr_engine="paddleocr",
                ocr_engine_version="3.0.0",
                ocr_confidence=0.91,
                processing_time_ms=1234,
                created_at=datetime(2026, 1, 1, 10, 0, 10, tzinfo=timezone.utc),
            ),
            OcrCascadeAttempt(
                id=1,
                document_id=1,
                page_id=1000,
                page_number=1,
                tier="tesseract",
                tier_index=1,
                success=True,
                duration_ms=412,
                confidence=0.31,
                chars=5,
                reason="no_improvement",
                created_at=datetime(2026, 1, 1, 10, 0, 5, tzinfo=timezone.utc),
            ),
            OcrCascadeAttempt(
                id=2,
                document_id=1,
                page_id=1000,
                page_number=1,
                tier="paddleocr",
                tier_index=2,
                success=True,
                duration_ms=891,
                confidence=0.91,
                chars=421,
                reason="ok",
                created_at=datetime(2026, 1, 1, 10, 0, 6, tzinfo=timezone.utc),
            ),
        ]
    )
    s.commit()

    steps = build_document_flow(s, document_id=1)
    kinds = [step["kind"] for step in steps]
    assert kinds[0] == "watcher.detected"
    assert kinds[-1] == "page.processed"
    assert any(k == "ingestion.committed" for k in kinds)
    assert any(k == "extraction_job" for k in kinds)
    # Steps are strictly ordered by timestamp.
    timestamps = [step["at"] for step in steps]
    assert timestamps == sorted(timestamps)
    # The page.processed step carries the full cascade trace.
    page_step = next(s for s in steps if s["kind"] == "page.processed")
    cascade = page_step["details"]["cascade_attempts"]
    assert [c["tier_index"] for c in cascade] == [1, 2]
    assert [c["tier"] for c in cascade] == ["tesseract", "paddleocr"]
    assert cascade[0]["success"] is True
    assert cascade[1]["success"] is True


def test_build_document_flow_empty_document():
    s = _make_session()
    Document(
        id=42, original_filename="empty.pdf", file_hash="y" * 64, status="pending"
    )
    s.commit()
    assert build_document_flow(s, document_id=42) == []
