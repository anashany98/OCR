"""Tests for P3 — geometric room detection.

The room detector is a thin wrapper around OpenCV's contour
analysis. The pure-Python helpers (shoelace area, regularity
score, px_per_metre conversion) are tested here with
hand-crafted polygons. The integration with a real plan image
is exercised in CI with the golden fixtures.
"""
from __future__ import annotations

import pytest

from app.services.plan_geometry import (
    DetectedRoom,
    _polygon_regularity,
    _px_per_metre,
    _shoelace_area,
)


# ---------------------------------------------------------------------------
# _shoelace_area
# ---------------------------------------------------------------------------


def test_shoelace_area_unit_square():
    polygon = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    assert _shoelace_area(polygon) == pytest.approx(1.0)


def test_shoelace_area_rectangle():
    polygon = [(0, 0), (4, 0), (4, 3), (0, 3), (0, 0)]
    assert _shoelace_area(polygon) == pytest.approx(12.0)


def test_shoelace_area_triangle():
    polygon = [(0, 0), (4, 0), (0, 3), (0, 0)]
    assert _shoelace_area(polygon) == pytest.approx(6.0)


def test_shoelace_area_empty_polygon():
    assert _shoelace_area([]) == 0.0
    assert _shoelace_area([(0, 0)]) == 0.0


# ---------------------------------------------------------------------------
# _polygon_regularity
# ---------------------------------------------------------------------------


def test_polygon_regularity_rectangle_is_one():
    polygon = [(0, 0), (4, 0), (4, 3), (0, 3), (0, 0)]
    assert _polygon_regularity(polygon) == pytest.approx(1.0)


def test_polygon_regularity_triangle_is_lower():
    polygon = [(0, 0), (4, 0), (0, 3), (0, 0)]
    # Triangle area = 6, bbox area = 12, ratio = 0.5
    assert _polygon_regularity(polygon) == pytest.approx(0.5)


def test_polygon_regularity_empty():
    assert _polygon_regularity([]) == 0.0
    assert _polygon_regularity([(0, 0)]) == 0.0


# ---------------------------------------------------------------------------
# _px_per_metre
# ---------------------------------------------------------------------------


def test_px_per_metre_1_to_100_at_300dpi():
    # 1:100 scale at 300 DPI: 1 cm on paper = 1 m real.
    # 300 DPI = 118.11 px/cm. 1 m = 11811 px.
    result = _px_per_metre(100, 300.0)
    assert result == pytest.approx(11811.02, abs=1.0)


def test_px_per_metre_1_to_50_at_300dpi():
    result = _px_per_metre(50, 300.0)
    assert result == pytest.approx(5905.51, abs=1.0)


def test_px_per_metre_returns_zero_for_bad_inputs():
    assert _px_per_metre(None, 300.0) == 0.0
    assert _px_per_metre(0, 300.0) == 0.0
    assert _px_per_metre(100, 0.0) == 0.0


# ---------------------------------------------------------------------------
# DetectedRoom dataclass
# ---------------------------------------------------------------------------


def test_detected_room_defaults():
    room = DetectedRoom(
        polygon=[(0, 0), (4, 0), (4, 3), (0, 3), (0, 0)],
        area_m2=12.0,
        centroid=(2.0, 1.5),
        perimeter_m=14.0,
        confidence=1.0,
    )
    assert room.area_m2 == 12.0
    assert len(room.polygon) == 5
