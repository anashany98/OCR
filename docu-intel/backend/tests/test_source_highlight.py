"""Tests for R4 — source highlight backend support.

The highlight module is a read-only query that returns the
document_id, page_number, block_id and bbox of a cited source
so the frontend can scroll to it and draw a highlight overlay.
The tests use a mocked DB session so the tests stay fast and
deterministic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.source_highlight import SourceHighlight, get_source_highlight


def test_source_highlight_defaults():
    h = SourceHighlight(
        document_id=42,
        page_number=2,
        block_id=None,
        bbox=None,
        excerpt="test excerpt",
    )
    assert h.document_id == 42
    assert h.page_number == 2
    assert h.bbox is None


def test_get_source_highlight_returns_none_for_missing_answer():
    db = MagicMock()
    db.get.return_value = None
    result = get_source_highlight(db, answer_id=999, source_index=0)
    assert result is None


def test_get_source_highlight_returns_none_for_out_of_range_index():
    db = MagicMock()
    answer = MagicMock()
    db.get.return_value = answer
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    result = get_source_highlight(db, answer_id=1, source_index=5)
    assert result is None


def test_get_source_highlight_returns_source_with_bbox():
    db = MagicMock()
    answer = MagicMock()
    db.get.return_value = answer

    source = MagicMock()
    source.document_id = 42
    source.page_number = 2
    source.block_id = 100
    source.excerpt = "test excerpt"

    block = MagicMock()
    block.bbox_x1 = 10.0
    block.bbox_y1 = 20.0
    block.bbox_x2 = 300.0
    block.bbox_y2 = 40.0

    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [source]
    db.get.side_effect = lambda cls, id: block if id == 100 else answer

    result = get_source_highlight(db, answer_id=1, source_index=0)
    assert result is not None
    assert result.document_id == 42
    assert result.page_number == 2
    assert result.block_id == 100
    assert result.bbox == (10.0, 20.0, 300.0, 40.0)
    assert result.excerpt == "test excerpt"


def test_get_source_highlight_returns_source_without_bbox():
    db = MagicMock()
    answer = MagicMock()
    db.get.return_value = answer

    source = MagicMock()
    source.document_id = 42
    source.page_number = 2
    source.block_id = None
    source.excerpt = "test excerpt"

    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [source]

    result = get_source_highlight(db, answer_id=1, source_index=0)
    assert result is not None
    assert result.bbox is None
