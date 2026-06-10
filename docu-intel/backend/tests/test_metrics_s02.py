"""Tests for S0.2 — Prometheus metrics by document type and OCR tier.

These tests are pure (no DB, no OCR engine) and verify that the
metric helpers record correctly and that the Prometheus text
output includes the expected labels.
"""
from __future__ import annotations

from app.services.metrics import (
    get_prometheus_text,
    track_ocr_tier_used,
    _ocr_tier_used,
    _ocr_tier_by_doc_type,
)


def _clear():
    _ocr_tier_used.clear()
    _ocr_tier_by_doc_type.clear()


def test_track_ocr_tier_used_records_tier_only():
    _clear()
    track_ocr_tier_used("tesseract")
    assert _ocr_tier_used.get("tesseract") == 1


def test_track_ocr_tier_used_records_tier_and_doc_type():
    _clear()
    track_ocr_tier_used("tesseract", document_type="presupuesto")
    assert _ocr_tier_used.get("tesseract") == 1
    assert _ocr_tier_by_doc_type.get(("tesseract", "presupuesto")) == 1


def test_track_ocr_tier_used_increments_per_doc_type():
    _clear()
    track_ocr_tier_used("paddleocr", document_type="plano")
    track_ocr_tier_used("paddleocr", document_type="plano")
    track_ocr_tier_used("paddleocr", document_type="factura")
    assert _ocr_tier_used.get("paddleocr") == 3
    assert _ocr_tier_by_doc_type.get(("paddleocr", "plano")) == 2
    assert _ocr_tier_by_doc_type.get(("paddleocr", "factura")) == 1


def test_track_ocr_tier_used_no_doc_type_is_ok():
    _clear()
    track_ocr_tier_used("pp_structure")
    assert _ocr_tier_used.get("pp_structure") == 1
    assert _ocr_tier_by_doc_type == {}


def test_prometheus_text_includes_tier_by_doc_type_label():
    _clear()
    track_ocr_tier_used("tesseract", document_type="presupuesto")
    text = get_prometheus_text()
    assert "docuintel_ocr_tier_by_doc_type" in text
    assert 'tier="tesseract"' in text
    assert 'document_type="presupuesto"' in text


def test_prometheus_text_includes_tier_used():
    _clear()
    track_ocr_tier_used("paddleocr")
    text = get_prometheus_text()
    assert "docuintel_ocr_tier_used_total" in text
    assert 'tier="paddleocr"' in text


def test_prometheus_text_omits_empty_labels():
    _clear()
    text = get_prometheus_text()
    assert "docuintel_ocr_tier_by_doc_type" not in text
