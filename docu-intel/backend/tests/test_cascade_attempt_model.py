"""Round-trip test for the OcrCascadeAttempt ORM model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.document import Document, DocumentPage
from app.models.ocr_cascade import OcrCascadeAttempt


def test_cascade_attempt_round_trips():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h"))
    s.add(DocumentPage(id=10, document_id=1, page_number=1))
    s.add(
        OcrCascadeAttempt(
            id=100,
            document_id=1,
            page_id=10,
            page_number=1,
            tier="paddleocr",
            tier_index=2,
            success=True,
            duration_ms=412,
            confidence=0.83,
            chars=421,
            reason="ok",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    s.commit()

    row = s.get(OcrCascadeAttempt, 100)
    assert row is not None
    assert row.tier == "paddleocr"
    assert row.tier_index == 2
    assert row.success is True
    assert row.duration_ms == 412
    assert row.confidence == 0.83
    assert row.chars == 421
    assert row.reason == "ok"
