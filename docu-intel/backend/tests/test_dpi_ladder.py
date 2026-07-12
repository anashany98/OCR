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

from app.parsers.pdf import _get_dpi_ladder, _DPI_MIN_CONFIDENCE, _DPI_MIN_TEXT_LENGTH, _ocr_is_usable
from app.services.metrics import _registry, track_ocr_dpi_escalation


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_dpi_ladder_contains_expected_values(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "pdf_ocr_dpi", 300)
    ladder = _get_dpi_ladder()
    assert ladder == [300, 400, 600]


def test_dpi_min_text_length_is_reasonable():
    assert _DPI_MIN_TEXT_LENGTH == 30


def test_dpi_min_confidence_is_reasonable():
    assert _DPI_MIN_CONFIDENCE == 0.55


# ---------------------------------------------------------------------------
# _ocr_is_usable
# ---------------------------------------------------------------------------


def test_ocr_is_usable_true_when_enough_text_and_confidence():
    assert _ocr_is_usable("Esta factura tiene suficiente texto", 0.80) is True


def test_ocr_is_usable_true_at_exact_thresholds():
    text = "a" * 30
    assert _ocr_is_usable(text, 0.55) is True


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


def _dpi_count(from_dpi: str, to_dpi: str) -> float:
    """Read the current value of the (from, to) cell of the
    prometheus_client Counter. Returns 0.0 if the label set has
    not been initialised yet (i.e. the transition was never
    recorded)."""
    child = _registry.OCR_DPI_ESCALATION._metrics.get((from_dpi, to_dpi))
    return child._value.get() if child is not None else 0.0


def test_track_ocr_dpi_escalation_records_transition():
    # prometheus_client Counters are monotonic across the test
    # session. We capture the baseline once and assert the
    # increment matches the number of calls.
    baseline_300_400 = _dpi_count("300", "400")
    baseline_400_600 = _dpi_count("400", "600")
    track_ocr_dpi_escalation(from_dpi=300, to_dpi=400)
    track_ocr_dpi_escalation(from_dpi=300, to_dpi=400)
    track_ocr_dpi_escalation(from_dpi=400, to_dpi=600)
    assert _dpi_count("300", "400") - baseline_300_400 == 2
    assert _dpi_count("400", "600") - baseline_400_600 == 1


def test_track_ocr_dpi_escalation_does_not_raise_on_zero():
    baseline = _dpi_count("0", "300")
    track_ocr_dpi_escalation(from_dpi=0, to_dpi=300)
    assert _dpi_count("0", "300") - baseline == 1
