"""Tests for O1 — DPI adaptativo escalonado (300→400→600).

The DPI ladder is a thin layer in ``parsers/pdf.py`` that
re-renders a scanned PDF page at progressively higher DPI when
Tier 1 produces a weak result (too few characters, low
confidence). The tests below verify the helper functions and
the metric tracking; the end-to-end integration (render +
cascade + re-render) is exercised in CI with a real PDF
fixture.
"""
from __future__ import annotations

from app.parsers.pdf import _DPI_LADDER, _DPI_MIN_CONFIDENCE, _DPI_MIN_TEXT_LENGTH, _ocr_is_usable
from app.services.metrics import track_ocr_dpi_escalation, _ocr_dpi_escalations


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_dpi_ladder_contains_expected_values():
    assert _DPI_LADDER == [300, 400, 600]


def test_dpi_min_text_length_is_reasonable():
    assert _DPI_MIN_TEXT_LENGTH == 30


def test_dpi_min_confidence_is_reasonable():
    assert _DPI_MIN_CONFIDENCE == 0.40


# ---------------------------------------------------------------------------
# _ocr_is_usable
# ---------------------------------------------------------------------------


def test_ocr_is_usable_true_when_enough_text_and_confidence():
    assert _ocr_is_usable("Esta factura tiene suficiente texto", 0.80) is True


def test_ocr_is_usable_true_at_exact_thresholds():
    text = "a" * 30
    assert _ocr_is_usable(text, 0.40) is True


def test_ocr_is_usable_false_when_text_too_short():
    assert _ocr_is_usable("corto", 0.80) is False


def test_ocr_is_usable_false_when_confidence_too_low():
    text = "a" * 50
    assert _ocr_is_usable(text, 0.30) is False


def test_ocr_is_usable_false_when_empty_text():
    assert _ocr_is_usable("", 0.80) is False
    assert _ocr_is_usable("   ", 0.80) is False


def test_ocr_is_usable_false_when_zero_confidence():
    text = "a" * 50
    assert _ocr_is_usable(text, 0.0) is False


# ---------------------------------------------------------------------------
# Metric tracking
# ---------------------------------------------------------------------------


def test_track_ocr_dpi_escalation_records_transition():
    _ocr_dpi_escalations.clear()
    track_ocr_dpi_escalation(from_dpi=300, to_dpi=400)
    track_ocr_dpi_escalation(from_dpi=300, to_dpi=400)
    track_ocr_dpi_escalation(from_dpi=400, to_dpi=600)
    assert _ocr_dpi_escalations.get(("300", "400")) == 2
    assert _ocr_dpi_escalations.get(("400", "600")) == 1


def test_track_ocr_dpi_escalation_does_not_raise_on_zero():
    _ocr_dpi_escalations.clear()
    track_ocr_dpi_escalation(from_dpi=0, to_dpi=300)
    assert _ocr_dpi_escalations.get(("0", "300")) == 1
