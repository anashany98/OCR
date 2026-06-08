"""Test the per-page digital / OCR decision in parse_pdf.

The parser must:
  - extract embedded text directly for digital pages (no OCR)
  - fall through to the OCR cascade for pages without embedded text
  - label each page's ocr_engine correctly (pymupdf vs cascade engine)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest

from app.ocr.base import OCRBlock, OCRResult


def _make_pdf_with_pages(path: Path, pages: list[str]) -> None:
    """Write a PDF with the given list of page texts. Empty string = scanned page."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            # Insert some real text so page.get_text() returns it.
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _fake_ocr_engine() -> MagicMock:
    """Mock cascade that returns a canned OCRResult only when called."""
    eng = MagicMock()
    eng.name = "tesseract"
    eng.extract.return_value = OCRResult(
        text="OCR TEXT",
        confidence=0.7,
        blocks=[OCRBlock(text="OCR TEXT", confidence=0.7, bbox=(0, 0, 100, 100))],
        engine="tesseract",
    )
    return eng


def test_digital_pages_skip_ocr(tmp_path: Path):
    pdf = tmp_path / "digital.pdf"
    _make_pdf_with_pages(
        pdf,
        [
            "Hello world this is the first page with plenty of text content",
            "Second page also has enough text to be classified as digital",
            "Third page again has more than thirty characters of text",
        ],
    )

    out_dir = tmp_path / "out"
    eng = _fake_ocr_engine()

    from app.parsers.pdf import parse_pdf

    doc = parse_pdf(pdf, out_dir, eng)
    assert len(doc.pages) == 3
    for page in doc.pages:
        assert page.ocr_engine == "pymupdf", f"expected pymupdf, got {page.ocr_engine}"
        assert page.ocr_confidence == 1.0
        assert page.text.strip(), "digital page should have text"
        assert all(b.source_engine == "pymupdf" for b in page.blocks)

    # OCR engine must NOT have been called for fully-digital PDFs.
    eng.extract.assert_not_called()


def test_scanned_pages_go_through_ocr(tmp_path: Path):
    pdf = tmp_path / "scanned.pdf"
    # All empty pages → all scanned.
    _make_pdf_with_pages(pdf, ["", "", ""])

    out_dir = tmp_path / "out"
    eng = _fake_ocr_engine()

    from app.parsers.pdf import parse_pdf

    doc = parse_pdf(pdf, out_dir, eng)
    assert len(doc.pages) == 3
    for page in doc.pages:
        assert page.ocr_engine == "tesseract", f"expected tesseract, got {page.ocr_engine}"
        assert page.ocr_confidence == 0.7
        assert page.text == "OCR TEXT"

    # OCR must have been called once per page.
    assert eng.extract.call_count == 3


def test_mixed_pdf_routes_per_page(tmp_path: Path):
    """A mixed PDF (digital + scanned pages) must use the fast path on
    digital pages and OCR only on scanned ones. This is the key
    improvement over the old all-or-nothing is_digital_pdf check."""
    pdf = tmp_path / "mixed.pdf"
    _make_pdf_with_pages(
        pdf,
        [
            "Digital page 1 with enough text to be detected as digital.",
            "",  # scanned
            "Digital page 3 also with enough text.",
            "",  # scanned
        ],
    )

    out_dir = tmp_path / "out"
    eng = _fake_ocr_engine()

    from app.parsers.pdf import parse_pdf

    doc = parse_pdf(pdf, out_dir, eng)
    assert len(doc.pages) == 4

    # Page 1: digital → pymupdf, no OCR
    assert doc.pages[0].ocr_engine == "pymupdf"
    assert "Digital page 1" in doc.pages[0].text

    # Page 2: scanned → tesseract
    assert doc.pages[1].ocr_engine == "tesseract"
    assert doc.pages[1].text == "OCR TEXT"

    # Page 3: digital → pymupdf
    assert doc.pages[2].ocr_engine == "pymupdf"
    assert "Digital page 3" in doc.pages[2].text

    # Page 4: scanned → tesseract
    assert doc.pages[3].ocr_engine == "tesseract"

    # OCR called exactly twice (only for the 2 scanned pages), not 4.
    assert eng.extract.call_count == 2, f"expected 2 OCR calls, got {eng.extract.call_count}"


def test_very_short_text_still_routes_to_ocr(tmp_path: Path):
    """Pages with < 30 chars of embedded text go to OCR (better
    confidence than trying to use a fragment)."""
    pdf = tmp_path / "short.pdf"
    _make_pdf_with_pages(pdf, ["hi"])  # only 2 chars

    out_dir = tmp_path / "out"
    eng = _fake_ocr_engine()

    from app.parsers.pdf import parse_pdf

    doc = parse_pdf(pdf, out_dir, eng)
    assert doc.pages[0].ocr_engine == "tesseract"
    assert eng.extract.call_count == 1


def test_scanned_pdf_pages_render_at_300_dpi_by_default(tmp_path: Path):
    pdf = tmp_path / "scanned.pdf"
    _make_pdf_with_pages(pdf, [""])
    out_dir = tmp_path / "out"
    eng = _fake_ocr_engine()

    from PIL import Image
    from app.parsers.pdf import parse_pdf

    doc = parse_pdf(pdf, out_dir, eng)
    rendered = Path(doc.pages[0].image_path)

    with Image.open(rendered) as image:
        width, height = image.size

    assert width == pytest.approx(595 * 300 / 72, abs=3)
    assert height == pytest.approx(842 * 300 / 72, abs=3)
