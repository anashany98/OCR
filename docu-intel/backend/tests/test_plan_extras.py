"""Tests for P1 (DZI tiles), P2 (plan symbols stub), P4 (line detection).

All three modules are pure (no ML, no GPU) and fail-safe. The
tests verify the data classes, the helper functions, and the
fail-safe behaviour without requiring OpenCV or Pillow to be
installed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.dzi_tiles import TILE_SIZE, generate_dzi_tiles
from app.services.plan_symbols import (
    DetectedSymbol,
    SUPPORTED_SYMBOL_CLASSES,
    detect_symbols,
)
from app.services.plan_line_detection import DetectedLine, detect_lines


# ---------------------------------------------------------------------------
# P1 — DZI tiles
# ---------------------------------------------------------------------------


def test_dzi_tiles_returns_none_for_missing_file():
    result = generate_dzi_tiles("/nonexistent.png", "/tmp/dzi")
    assert result is None


def test_dzi_tiles_returns_none_without_pillow(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules, "PIL", raising=False)
    monkeypatch.delitem(sys.modules, "PIL.Image", raising=False)
    result = generate_dzi_tiles("/fake.png", "/tmp/dzi")
    assert result is None


def test_dzi_tile_size_constant():
    assert TILE_SIZE == 256


# ---------------------------------------------------------------------------
# P2 — Plan symbols
# ---------------------------------------------------------------------------


def test_detected_symbol_defaults():
    sym = DetectedSymbol(
        symbol_class="electrical_outlet",
        bbox=(10.0, 20.0, 30.0, 40.0),
        confidence=0.85,
        page_number=1,
    )
    assert sym.symbol_class == "electrical_outlet"
    assert sym.confidence == 0.85


def test_detect_symbols_returns_empty_list():
    """The stub always returns an empty list."""
    result = detect_symbols("/fake.png", page_number=1)
    assert result == []


def test_supported_symbol_classes_is_nonempty():
    assert len(SUPPORTED_SYMBOL_CLASSES) > 0
    assert "electrical_outlet" in SUPPORTED_SYMBOL_CLASSES
    assert "door" in SUPPORTED_SYMBOL_CLASSES


# ---------------------------------------------------------------------------
# P4 — Line detection
# ---------------------------------------------------------------------------


def test_detected_line_defaults():
    line = DetectedLine(
        x1=0.0, y1=0.0, x2=100.0, y2=0.0,
        length_px=100.0, angle_deg=0.0,
    )
    assert line.length_px == 100.0
    assert line.angle_deg == 0.0


def test_detect_lines_returns_empty_without_opencv(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules, "cv2", raising=False)
    result = detect_lines("/fake.png")
    assert result == []


def test_detect_lines_returns_empty_for_missing_file():
    result = detect_lines("/nonexistent.png")
    assert result == []
