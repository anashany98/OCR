"""Tests for the quality evaluation logic, especially the digital-PDF
auto-approve shortcut."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.quality import QualityResult, evaluate_document_quality


def _make_document(**overrides):
    doc = MagicMock()
    doc.id = 1
    doc.status = overrides.get("status", "processing")
    doc.document_type = overrides.get("document_type", "factura")
    doc.confidence = overrides.get("confidence", 0.85)
    return doc


def _make_pages(ocr_confidences):
    pages = []
    for i, conf in enumerate(ocr_confidences, 1):
        page = MagicMock()
        page.id = i
        page.ocr_confidence = conf
        page.page_status = "processed"
        pages.append(page)
    return pages


def _patch_db(pages, *, failed_page=False):
    db = MagicMock()
    call_count = [0]

    def _scalar(query):
        call_count[0] += 1
        if failed_page and call_count[0] == 1:
            mock = MagicMock()
            mock.id = 999
            return mock
        return None

    def _scalars(query):
        stmt = str(query)
        result = MagicMock()
        if "document_page" in stmt.lower():
            result.all.return_value = pages
        else:
            result.all.return_value = []
        return result

    db.scalar.side_effect = _scalar
    db.scalars.side_effect = _scalars
    return db


LONG_TEXT = "Factura F-001 emitida por proveedor ABC. Total: 1200 EUR. Fecha: 01/06/2026. Detalle del servicio prestado."


class TestDigitalPdfAutoApprove:
    """Digital PDFs (ocr_confidence=1.0) should auto-approve even when
    classification confidence is below the normal threshold."""

    def test_digital_pdf_auto_approves_with_low_classification_and_business_review(self):
        doc = _make_document(confidence=0.65)
        pages = _make_pages([1.0])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT,
            page_count=1,
            business_needs_review=True,
        )

        assert result.status == "processed_ok"
        assert not result.needs_review

    def test_digital_pdf_auto_approves_with_low_classification_no_review(self):
        doc = _make_document(confidence=0.70, document_type="pedido")
        pages = _make_pages([1.0])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text="Pedido P-456 para Cliente ABC. Total: 500 EUR. Fecha: 10/06/2026.",
            page_count=1,
        )

        assert result.status == "processed_ok"
        assert not result.needs_review

    def test_scanned_pdf_needs_high_classification_for_auto_approve(self):
        """Scanned PDF with low classification and business review
        should NOT auto-approve."""
        doc = _make_document(confidence=0.65)
        pages = _make_pages([0.85])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT,
            page_count=1,
            business_needs_review=True,
        )

        # business_needs_review + invoice_date_missing flag → needs_human_review
        assert result.needs_review

    def test_scanned_pdf_auto_approves_when_classification_high_enough(self):
        doc = _make_document(confidence=0.85)
        pages = _make_pages([0.92])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT,
            page_count=1,
        )

        assert result.status == "processed_ok"
        assert not result.needs_review

    def test_digital_pdf_fails_when_no_text(self):
        doc = _make_document(confidence=0.85)
        pages = _make_pages([1.0])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text="",
            page_count=1,
        )

        assert result.status == "processed_low_quality"
        assert result.needs_review

    def test_digital_pdf_fails_when_page_failed(self):
        doc = _make_document(confidence=0.85)
        pages = _make_pages([1.0])
        db = _patch_db(pages, failed_page=True)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT,
            page_count=1,
        )

        assert result.status == "needs_human_review"
        assert result.needs_review

    def test_scanned_pdf_with_low_ocr_needs_review(self):
        doc = _make_document(confidence=0.85)
        pages = _make_pages([0.5])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT,
            page_count=1,
            low_ocr_confidences=[0.5],
        )

        assert result.status == "processed_low_quality"
        assert result.needs_review

    def test_multipage_pdf_with_one_low_ocr_page_stays_processed_when_text_is_good(self):
        doc = _make_document(confidence=0.88, document_type="factura")
        pages = _make_pages([0.91, 0.52, 0.93, 0.89])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT * 4,
            page_count=4,
            low_ocr_confidences=[0.52],
        )

        assert "partial_low_ocr_confidence" in result.flags
        assert "low_ocr_confidence" not in result.flags
        assert result.status == "processed_ok"
        assert not result.needs_review

    def test_digital_pdf_unknown_type_not_auto_approved(self):
        doc = _make_document(confidence=0.50, document_type="desconocido")
        pages = _make_pages([1.0])
        db = _patch_db(pages)

        result = evaluate_document_quality(
            db,
            doc,
            text=LONG_TEXT,
            page_count=1,
        )

        assert result.status == "needs_human_review"
        assert result.needs_review


class TestQualityResult:
    def test_needs_review_statuses(self):
        for status in ("processed_low_quality", "processed_missing_fields", "needs_human_review", "failed"):
            r = QualityResult(status=status, score=0.5, flags=[])
            assert r.needs_review is True

    def test_ok_status_no_review(self):
        r = QualityResult(status="processed_ok", score=0.9, flags=[])
        assert r.needs_review is False
