"""Tests for O3 — layout-aware text extraction for multi-column PDFs.

The layout parser is a thin wrapper around PyMuPDF's block
extraction with a multi-column heuristic. The pure-Python parts
(gap detection, column re-ordering) are tested here with
hand-crafted ``TextBlock`` objects so the tests stay
deterministic and fast. The integration with a real PDF is
exercised in CI with the golden fixtures.
"""
from __future__ import annotations

import pytest

from app.services.layout_parser import (
    LayoutResult,
    TextBlock,
    _detect_multicolumn,
    _find_vertical_gap,
    _reorder_by_columns,
)


# ---------------------------------------------------------------------------
# TextBlock
# ---------------------------------------------------------------------------


def test_textblock_defaults():
    b = TextBlock(text="hello", x0=0, y0=0, x1=100, y1=20)
    assert b.reading_order == 0


# ---------------------------------------------------------------------------
# _find_vertical_gap
# ---------------------------------------------------------------------------


def test_find_vertical_gap_returns_none_when_no_gap():
    blocks = [
        TextBlock("a", 0, 0, 50, 20),
        TextBlock("b", 50, 0, 100, 20),
    ]
    assert _find_vertical_gap(blocks, 100.0) is None


def test_find_vertical_gap_detects_gap_in_middle():
    # Two blocks on left and right with a 20% gap in the middle.
    blocks = [
        TextBlock("left", 0, 0, 35, 20),
        TextBlock("right", 65, 0, 100, 20),
    ]
    gap = _find_vertical_gap(blocks, 100.0)
    assert gap is not None
    # The gap should be around x=50 (middle of the page).
    assert 40 < gap < 60


def test_find_vertical_gap_returns_none_for_empty_blocks():
    assert _find_vertical_gap([], 100.0) is None


def test_find_vertical_gap_returns_none_for_zero_width():
    assert _find_vertical_gap([TextBlock("a", 0, 0, 50, 20)], 0.0) is None


# ---------------------------------------------------------------------------
# _detect_multicolumn
# ---------------------------------------------------------------------------


def test_detect_multicolumn_returns_false_for_single_column():
    # All blocks on the left side.
    blocks = [
        TextBlock("a", 0, 0, 40, 20),
        TextBlock("b", 0, 20, 40, 40),
        TextBlock("c", 0, 40, 40, 60),
        TextBlock("d", 0, 60, 40, 80),
        TextBlock("e", 0, 80, 40, 100),
        TextBlock("f", 0, 100, 40, 120),
    ]

    class FakePage:
        class rect:
            width = 100.0
            height = 200.0

    is_multi, count, gap = _detect_multicolumn(FakePage(), blocks)
    assert is_multi is False
    assert count == 1


def test_detect_multicolumn_returns_true_for_two_columns():
    # Blocks evenly split between left and right with a gap.
    blocks = [
        TextBlock("L1", 0, 0, 35, 20),
        TextBlock("L2", 0, 20, 35, 40),
        TextBlock("L3", 0, 40, 35, 60),
        TextBlock("R1", 65, 0, 100, 20),
        TextBlock("R2", 65, 20, 100, 40),
        TextBlock("R3", 65, 40, 100, 60),
    ]

    class FakePage:
        class rect:
            width = 100.0
            height = 200.0

    is_multi, count, gap = _detect_multicolumn(FakePage(), blocks)
    assert is_multi is True
    assert count == 2
    assert gap > 0


def test_detect_multicolumn_returns_false_for_too_few_blocks():
    blocks = [TextBlock("a", 0, 0, 50, 20), TextBlock("b", 50, 0, 100, 20)]

    class FakePage:
        class rect:
            width = 100.0
            height = 200.0

    is_multi, count, gap = _detect_multicolumn(FakePage(), blocks)
    assert is_multi is False


# ---------------------------------------------------------------------------
# _reorder_by_columns
# ---------------------------------------------------------------------------


def test_reorder_by_columns_left_first_then_right():
    blocks = [
        TextBlock("R1", 65, 0, 100, 20),
        TextBlock("L1", 0, 0, 35, 20),
        TextBlock("L2", 0, 20, 35, 40),
        TextBlock("R2", 65, 20, 100, 40),
    ]
    reordered = _reorder_by_columns(blocks, gap_x=50.0)
    texts = [b.text for b in reordered]
    assert texts == ["L1", "L2", "R1", "R2"]


def test_reorder_by_columns_preserves_y_order_within_column():
    blocks = [
        TextBlock("L3", 0, 40, 35, 60),
        TextBlock("L1", 0, 0, 35, 20),
        TextBlock("L2", 0, 20, 35, 40),
    ]
    reordered = _reorder_by_columns(blocks, gap_x=50.0)
    texts = [b.text for b in reordered]
    assert texts == ["L1", "L2", "L3"]


def test_reorder_by_columns_assigns_reading_order():
    blocks = [
        TextBlock("R1", 65, 0, 100, 20),
        TextBlock("L1", 0, 0, 35, 20),
    ]
    reordered = _reorder_by_columns(blocks, gap_x=50.0)
    assert reordered[0].reading_order == 0
    assert reordered[1].reading_order == 1
    assert reordered[0].text == "L1"
    assert reordered[1].text == "R1"
