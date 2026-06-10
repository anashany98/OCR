"""Tests for S0.2 — Prometheus metrics by document type and OCR tier.

These tests are pure (no DB, no OCR engine) and verify that the
metric helpers record correctly and that the Prometheus text
output includes the expected labels.

The original tests read the in-memory ``_ocr_tier_used`` and
``_ocr_tier_by_doc_type`` dicts directly. After the migration
to ``prometheus_client``, the canonical way to read the
current value of a labelled counter is via
``Counter._metrics[labels]._value.get()``. We keep the test
intent (``assert N calls produced N increments``) but read
through the registry.
"""
from __future__ import annotations

from app.services.metrics import (
    _registry,
    get_prometheus_text,
    track_ocr_tier_used,
)


def _tier_count(tier: str) -> float:
    child = _registry.OCR_TIER_USED._metrics.get((tier,))
    return child._value.get() if child is not None else 0.0


def _tier_doc_count(tier: str, doc_type: str) -> float:
    child = _registry.OCR_TIER_BY_DOC_TYPE._metrics.get((tier, doc_type))
    return child._value.get() if child is not None else 0.0


def test_track_ocr_tier_used_records_tier_only():
    baseline = _tier_count("tesseract")
    track_ocr_tier_used("tesseract")
    assert _tier_count("tesseract") - baseline == 1


def test_track_ocr_tier_used_records_tier_and_doc_type():
    base_tier = _tier_count("tesseract")
    base_pair = _tier_doc_count("tesseract", "presupuesto")
    track_ocr_tier_used("tesseract", document_type="presupuesto")
    assert _tier_count("tesseract") - base_tier == 1
    assert _tier_doc_count("tesseract", "presupuesto") - base_pair == 1


def test_track_ocr_tier_used_increments_per_doc_type():
    base_tier = _tier_count("paddleocr")
    base_plano = _tier_doc_count("paddleocr", "plano")
    base_factura = _tier_doc_count("paddleocr", "factura")
    track_ocr_tier_used("paddleocr", document_type="plano")
    track_ocr_tier_used("paddleocr", document_type="plano")
    track_ocr_tier_used("paddleocr", document_type="factura")
    assert _tier_count("paddleocr") - base_tier == 3
    assert _tier_doc_count("paddleocr", "plano") - base_plano == 2
    assert _tier_doc_count("paddleocr", "factura") - base_factura == 1


def test_track_ocr_tier_used_no_doc_type_is_ok():
    base_tier = _tier_count("pp_structure")
    track_ocr_tier_used("pp_structure")
    # The no-doc-type path must not create a label set with
    # ``document_type="unknown"``; the per-doc-type counter is
    # left untouched.
    assert _tier_doc_count("pp_structure", "unknown") == 0.0
    assert _tier_count("pp_structure") - base_tier == 1


def test_prometheus_text_includes_tier_by_doc_type_label():
    track_ocr_tier_used("tesseract", document_type="presupuesto")
    text = get_prometheus_text().decode("utf-8")
    assert "docuintel_ocr_tier_by_doc_type" in text
    assert 'tier="tesseract"' in text
    assert 'document_type="presupuesto"' in text


def test_prometheus_text_includes_tier_used():
    track_ocr_tier_used("paddleocr")
    text = get_prometheus_text().decode("utf-8")
    assert "docuintel_ocr_tier_used_total" in text
    assert 'tier="paddleocr"' in text


def test_prometheus_text_is_valid_openmetrics():
    """The new ``render_metrics()`` returns the standard
    prometheus_client exposition format. A few sanity checks:
    the content type prefix, the metric name, the value.
    """
    track_ocr_tier_used("tesseract", document_type="presupuesto")
    track_ocr_tier_used("paddleocr")  # tier-only path
    text = get_prometheus_text().decode("utf-8")
    # prometheus_client appends ``_total`` to every Counter
    # automatically, so the metric name in the payload is
    # ``docuintel_ocr_tier_by_doc_type_total``.
    assert "docuintel_ocr_tier_by_doc_type_total{" in text
    assert "docuintel_ocr_tier_used_total{" in text
    # The payload contains the standard prometheus_client
    # "# HELP <name> <desc>" / "# TYPE <name> counter" preamble.
    assert "# HELP docuintel_ocr_tier" in text
