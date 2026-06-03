"""Tests for the per-page ocr_engine tracking and the admin stats endpoint."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import DocumentPage


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Per-page engine labels
# ---------------------------------------------------------------------------


def test_parse_pdf_digital_records_pymupdf_per_page(db, tmp_path):
    """For a digital-only PDF, every page must be labelled ocr_engine='pymupdf'."""
    from app.parsers.pdf import parse_pdf
    from app.ocr.paddle import PaddleOCREngine

    pdf_path = _build_digital_pdf(tmp_path / "digital.pdf")
    output_dir = tmp_path / "out"
    doc = parse_pdf(pdf_path, output_dir, PaddleOCREngine())
    assert len(doc.pages) == 3
    for page in doc.pages:
        assert page.ocr_engine == "pymupdf"


def test_parse_pdf_mixed_routes_ocr_pages_to_paddleocr(db, tmp_path):
    """For a mixed PDF, scanned pages must be labelled ocr_engine='paddleocr'.

    Slow integration test: loads the PaddleOCR model. Skipped unless the
    RUN_SLOW_OCR_TESTS env var is set.
    """
    import os

    if not os.environ.get("RUN_SLOW_OCR_TESTS"):
        pytest.skip("set RUN_SLOW_OCR_TESTS=1 to run the PaddleOCR integration test")
    pytest.importorskip("paddleocr")
    from app.ocr.paddle import PaddleOCREngine
    from app.parsers.pdf import parse_pdf

    pdf_path = _build_mixed_pdf(tmp_path / "mixed.pdf")
    output_dir = tmp_path / "out"
    doc = parse_pdf(pdf_path, output_dir, PaddleOCREngine())
    engines = {p.page_number: p.ocr_engine for p in doc.pages}
    assert "pymupdf" in engines.values()
    assert any(e in {"paddleocr", "empty"} for e in engines.values())


# ---------------------------------------------------------------------------
# Admin stats endpoint
# ---------------------------------------------------------------------------


def test_ocr_stats_endpoint_groups_by_engine(db):
    """The stats endpoint returns counts and share per engine."""
    from app.api.routes.admin_ocr_stats import ocr_stats

    db.add_all(
        [
            DocumentPage(document_id=1, page_number=1, text="x", ocr_engine="pymupdf"),
            DocumentPage(document_id=1, page_number=2, text="x", ocr_engine="pymupdf"),
            DocumentPage(document_id=1, page_number=3, text="x", ocr_engine="paddleocr"),
            DocumentPage(document_id=1, page_number=4, text="x", ocr_engine=None),  # unset
            DocumentPage(document_id=1, page_number=5, text="x", ocr_engine="empty"),
        ]
    )
    db.commit()

    result = ocr_stats(db)
    assert result["total_pages"] == 5
    assert result["counts"]["pymupdf"] == 2
    assert result["counts"]["paddleocr"] == 1
    assert result["counts"]["unset"] == 1
    assert result["counts"]["empty"] == 1
    assert result["share"]["pymupdf"] == 0.4
    assert result["share"]["paddleocr"] == 0.2
    assert result["share"]["empty"] == 0.2


# ---------------------------------------------------------------------------
# PDF fixtures
# ---------------------------------------------------------------------------


def _build_digital_pdf(path: Path) -> Path:
    """Create a 3-page PDF with real digital text on every page."""
    import fitz

    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        # 200 chars of text per page — well above the 30-char threshold.
        page.insert_text((72, 72), f"Page {i + 1} — " + "lorem ipsum " * 14)
    doc.save(str(path))
    doc.close()
    return path


def _build_mixed_pdf(path: Path) -> Path:
    """Create a 2-page PDF: one page with text, one rendered as an image (no text)."""
    import fitz

    doc = fitz.open()
    # Page 1: real digital text
    page_with_text = doc.new_page()
    page_with_text.insert_text((72, 72), "Digital page " + "lorem ipsum " * 20)
    # Page 2: blank page (no text inserted)
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(scope="module", autouse=True)
def _clean_fitz_lock():
    """PaddleOCR holds a global lock; we don't want it lingering across tests."""
    yield
    # Best-effort cleanup of the lockfile PyMuPDF / PaddleOCR may create in tmp.
    lock = Path("/tmp") / "docuintel_paddleocr_init.lock"
    if lock.exists():
        try:
            lock.unlink()
        except OSError:
            pass
