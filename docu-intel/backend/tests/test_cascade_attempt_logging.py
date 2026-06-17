"""Tests for the OcrCascadeAttempt recorder hook on CascadingOCREngine.

We exercise the cascade with fake engines and a fake recorder
(no DB, no tesseract) so the test runs on any platform. The contract
we verify is exactly what ``_record_attempt`` was designed to do:
every tier tried is reported, success and failure are both logged,
and a recorder that raises must never propagate.

The recorder receives ``document_id`` + ``page_number`` (not
``page_id``) because at the moment the parser calls the cascade the
``DocumentPage`` row may not exist yet. The recorder is responsible
for resolving ``page_id`` via a lookup — see
``app.parsers.pdf._build_cascade_recorder`` for the production
implementation.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.document import Document, DocumentPage
from app.models.ocr_cascade import OcrCascadeAttempt
from app.ocr.base import OCRResult
from app.ocr.cascading import CascadingOCREngine


class _FakeEngine:
    """Stand-in OCR engine. Returns a fixed text/confidence and tracks calls."""

    def __init__(self, name: str, text: str = "x" * 60, confidence: float = 0.9):
        self.name = name
        self._text = text
        self._confidence = confidence
        self.call_count = 0

    def extract(self, image_path: Path) -> OCRResult:
        self.call_count += 1
        return OCRResult(
            text=self._text, confidence=self._confidence, blocks=[], engine=self.name
        )


class _BoomEngine:
    name = "boom"

    def extract(self, image_path: Path) -> OCRResult:
        raise RuntimeError("kaboom")


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _fake_image(tmp_path) -> Path:
    p = tmp_path / "page.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def _make_recorder(s, page_lookup: dict[int, int] | None = None):
    """Build a recorder that resolves ``page_id`` from a lookup table.

    ``page_lookup`` maps ``page_number`` -> ``page_id``. When not
    provided, the recorder looks it up via SQLAlchemy (this mirrors
    the production behaviour).
    """

    def _record(row: dict) -> None:
        document_id = row.pop("document_id")
        page_number = row.pop("page_number")
        if page_lookup is not None:
            page_id = page_lookup.get(page_number)
        else:
            page = s.scalars(
                select(DocumentPage).where(
                    DocumentPage.document_id == document_id,
                    DocumentPage.page_number == page_number,
                )
            ).first()
            page_id = page.id if page else None
        s.add(
            OcrCascadeAttempt(
                document_id=document_id,
                page_id=page_id,
                page_number=page_number,
                **row,
            )
        )
        s.commit()

    return _record


def test_cascade_records_every_tier_attempt(tmp_path):
    """The cascade must log both primary and fallback."""
    s, _ = _session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h"))
    s.add(DocumentPage(id=10, document_id=1, page_number=1))
    s.commit()

    primary = _FakeEngine("tesseract", text="x" * 5, confidence=0.4)  # weak
    fallback = _FakeEngine("paddleocr", text="x" * 80, confidence=0.9)
    cascade = CascadingOCREngine(primary=primary, fallback=fallback)
    cascade.current_document_id = 1
    cascade.current_page_number = 1
    cascade.attempt_recorder = _make_recorder(s, page_lookup={1: 10})

    cascade.extract(_fake_image(tmp_path))

    rows = s.query(OcrCascadeAttempt).order_by(OcrCascadeAttempt.tier_index).all()
    assert [r.tier for r in rows] == ["tesseract", "paddleocr"]
    # ``success`` reflects whether the engine **executed** without
    # raising, not whether the result won the cascade. The winner
    # is identified by ``DocumentPage.ocr_engine``.
    assert rows[0].success is True
    assert rows[0].tier_index == 1
    assert rows[1].success is True
    assert rows[1].tier_index == 2
    assert rows[0].document_id == 1
    assert rows[0].page_id == 10
    assert rows[0].page_number == 1


def test_cascade_records_pp_structure_attempt(tmp_path):
    """When Tier 3 is wired in and Tier 2 is weak, Tier 3 is also recorded."""
    s, _ = _session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h"))
    s.add(DocumentPage(id=10, document_id=1, page_number=1))
    s.commit()

    primary = _FakeEngine("tesseract", text="x" * 5, confidence=0.4)
    fallback = _FakeEngine("paddleocr", text="x" * 5, confidence=0.4)  # also weak
    pp_structure = _FakeEngine("pp_structure", text="x" * 100, confidence=0.95)
    cascade = CascadingOCREngine(
        primary=primary, fallback=fallback, pp_structure=pp_structure
    )
    cascade.current_document_id = 1
    cascade.current_page_number = 1
    cascade.attempt_recorder = _make_recorder(s, page_lookup={1: 10})

    cascade.extract(_fake_image(tmp_path))

    tiers = [
        r.tier
        for r in s.query(OcrCascadeAttempt).order_by(OcrCascadeAttempt.tier_index)
    ]
    assert tiers == ["tesseract", "paddleocr", "pp_structure"]


def test_recorder_exception_does_not_break_ocr(tmp_path):
    """A recorder that raises must never propagate into the OCR call."""
    primary = _FakeEngine("tesseract", text="x" * 80, confidence=0.9)
    fallback = _FakeEngine("paddleocr", text="x" * 80, confidence=0.9)
    cascade = CascadingOCREngine(primary=primary, fallback=fallback)
    cascade.attempt_recorder = lambda row: (_ for _ in ()).throw(RuntimeError("db down"))

    # Should not raise. The cascade still produces a result.
    result = cascade.extract(_fake_image(tmp_path))
    assert result.text == "x" * 80


def test_recorder_is_noop_without_context(tmp_path):
    """When the parser did not set the per-page context, the recorder is silent."""
    primary = _FakeEngine("tesseract", text="x" * 80, confidence=0.9)
    fallback = _FakeEngine("paddleocr", text="x" * 80, confidence=0.9)
    cascade = CascadingOCREngine(primary=primary, fallback=fallback)
    # No ``current_document_id`` / ``current_page_number`` set.
    captured: list[dict] = []
    cascade.attempt_recorder = lambda row: captured.append(row)

    cascade.extract(_fake_image(tmp_path))
    assert captured == []


def test_primary_exception_is_recorded_and_re_raised(tmp_path):
    """A primary engine exception must be logged with reason=exception."""
    s, _ = _session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h"))
    s.add(DocumentPage(id=10, document_id=1, page_number=1))
    s.commit()

    primary = _BoomEngine()
    fallback = _FakeEngine("paddleocr", text="x" * 80, confidence=0.9)
    cascade = CascadingOCREngine(primary=primary, fallback=fallback)
    cascade.current_document_id = 1
    cascade.current_page_number = 1
    cascade.attempt_recorder = _make_recorder(s, page_lookup={1: 10})

    with pytest.raises(RuntimeError, match="kaboom"):
        cascade.extract(_fake_image(tmp_path))

    rows = s.query(OcrCascadeAttempt).all()
    assert len(rows) == 1
    assert rows[0].tier == "boom"
    assert rows[0].tier_index == 1
    assert rows[0].success is False
    assert rows[0].reason == "exception"
    assert rows[0].error_message == "kaboom"


def test_recorder_call_count_for_short_circuit(tmp_path):
    """When the primary is acceptable, the fallback is not invoked."""
    primary = _FakeEngine("tesseract", text="x" * 80, confidence=0.9)
    fallback = MagicMock(name="fallback")
    fallback.name = "paddleocr"
    cascade = CascadingOCREngine(primary=primary, fallback=fallback)
    cascade.current_document_id = 1
    cascade.current_page_number = 1
    cascade.attempt_recorder = MagicMock()

    cascade.extract(_fake_image(tmp_path))

    assert fallback.extract.call_count == 0
    # Only the primary attempt was recorded.
    assert cascade.attempt_recorder.call_count == 1
