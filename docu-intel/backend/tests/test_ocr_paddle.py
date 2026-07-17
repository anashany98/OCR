"""
Unit tests for app.ocr.paddle
Tests the OCR engine helpers and parsing logic without requiring GPU inference.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.ocr.paddle import (
    PaddleOCREngine,
    OCRBlock,
    OCRResult,
    _get_gpu_device,
    gpu_has_headroom,
    _polygon_to_bbox,
)


class TestGetGpuDevice:
    """Tests for _get_gpu_device() function."""

    def test_returns_none_when_cuda_not_set(self, monkeypatch):
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
        assert _get_gpu_device() is None

    def test_returns_none_when_cuda_empty(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
        assert _get_gpu_device() is None

    def test_returns_first_device_single_gpu(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
        assert _get_gpu_device() == "0"

    def test_returns_first_device_multi_gpu(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
        assert _get_gpu_device() == "0"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", " 1 ")
        assert _get_gpu_device() == "1"

    def test_returns_none_for_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "   ")
        assert _get_gpu_device() is None


class TestGpuHeadroom:
    def test_returns_false_when_cuda_is_not_visible(self, monkeypatch):
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
        assert gpu_has_headroom(1) is False

    def test_accepts_gpu_with_sufficient_free_memory(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "4096\n", ""),
        )
        assert gpu_has_headroom(2048) is True

    def test_rejects_gpu_without_enough_free_memory(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "1024\n", ""),
        )
        assert gpu_has_headroom(2048) is False


class TestPolygonToBbox:
    """Tests for _polygon_to_bbox() function."""

    def test_returns_none_for_non_list(self):
        assert _polygon_to_bbox("not a list") is None
        assert _polygon_to_bbox(42) is None
        assert _polygon_to_bbox(None) is None

    def test_bbox_from_rectangle_polygon(self):
        polygon = [[0, 0], [100, 0], [100, 50], [0, 50]]
        assert _polygon_to_bbox(polygon) == (0.0, 0.0, 100.0, 50.0)

    def test_bbox_from_any_polygon(self):
        polygon = [[10, 20], [50, 10], [90, 30], [60, 80]]
        result = _polygon_to_bbox(polygon)
        assert result == (10.0, 10.0, 90.0, 80.0)

    def test_single_point(self):
        polygon = [[50, 50]]
        assert _polygon_to_bbox(polygon) == (50.0, 50.0, 50.0, 50.0)

    def test_empty_list_returns_none(self):
        assert _polygon_to_bbox([]) is None

    def test_returns_none_on_invalid_point_structure(self):
        assert _polygon_to_bbox([["a", "b"]]) is None
        assert _polygon_to_bbox([[]]) is None


class TestOcrBlock:
    """Tests for OCRBlock dataclass."""

    def test_ocrblock_with_all_fields(self):
        block = OCRBlock(text="Hello", confidence=0.95, bbox=(0, 0, 100, 50))
        assert block.text == "Hello"
        assert block.confidence == 0.95
        assert block.bbox == (0, 0, 100, 50)

    def test_ocrblock_with_none_bbox(self):
        block = OCRBlock(text="Hello", confidence=0.95, bbox=None)
        assert block.bbox is None


class TestOcrResult:
    """Tests for OCRResult dataclass."""

    def test_ocrresult_with_blocks(self):
        blocks = [
            OCRBlock(text="Line 1", confidence=0.9, bbox=(0, 0, 100, 20)),
            OCRBlock(text="Line 2", confidence=0.8, bbox=(0, 20, 100, 40)),
        ]
        result = OCRResult(text="Line 1\nLine 2", confidence=0.85, blocks=blocks)
        assert len(result.blocks) == 2
        assert result.confidence == 0.85

    def test_ocrresult_empty(self):
        result = OCRResult(text="", confidence=None, blocks=[])
        assert result.blocks == []
        assert result.confidence is None


class TestPaddleOcrEngineParseLine:
    """Tests for PaddleOCREngine._parse_ocr_line() method.

    Uses a mock engine so we don't need paddleocr installed.
    """

    @pytest.fixture
    def engine(self):
        """Create engine with mocked _engine to avoid paddleocr import."""
        eng = object.__new__(PaddleOCREngine)
        mock_engine = MagicMock()
        eng._engine = mock_engine
        return eng

    def test_parses_list_format_with_text_and_confidence(self, engine):
        """PaddleOCR 3.x returns [polygon, [text, confidence]] format."""
        line = [[[0, 0], [100, 0], [100, 50], [0, 50]], ["Hello World", 0.92]]
        result = engine._parse_ocr_line(line)
        assert result is not None
        text, confidence, bbox = result
        assert text == "Hello World"
        assert confidence == 0.92
        assert bbox == (0.0, 0.0, 100.0, 50.0)

    def test_parses_list_format_with_float_confidence(self, engine):
        line = [[[10, 20], [50, 20], [50, 60], [10, 60]], ["Test", 0.85]]
        result = engine._parse_ocr_line(line)
        assert result is not None
        text, confidence, bbox = result
        assert confidence == 0.85

    def test_parses_list_format_with_insufficient_length(self, engine):
        """payload with only text, no confidence - falls back to str(payload)."""
        line = [[[0, 0], [100, 0], [100, 50], [0, 50]], ["Only text"]]
        result = engine._parse_ocr_line(line)
        assert result is not None
        text, confidence, bbox = result
        # payload has only 1 element, so falls to else: text = str(payload)
        assert text == "['Only text']"
        assert confidence == 0.0

    def test_parses_list_format_with_empty_payload(self, engine):
        line = [[[0, 0], [100, 0], [100, 50], [0, 50]], []]
        result = engine._parse_ocr_line(line)
        assert result is not None
        text, confidence, bbox = result
        # payload is empty list [], str([]) -> "[]"
        assert text == "[]"
        assert confidence == 0.0

    def test_returns_none_for_non_list_line(self, engine):
        """Line that doesn't match list format or object attributes."""
        result = engine._parse_ocr_line("invalid")
        assert result is None

    def test_parses_object_with_text_and_score(self, engine):
        """Object with text and score attributes (2.x format)."""

        class MockLine:
            text = "Hello"
            score = 0.88
            polygon = [[0, 0], [100, 0], [100, 50], [0, 50]]

        result = engine._parse_ocr_line(MockLine())
        assert result is not None
        text, confidence, bbox = result
        assert text == "Hello"
        assert confidence == 0.88
        assert bbox == (0.0, 0.0, 100.0, 50.0)

    def test_parses_object_with_bbox_instead_of_polygon(self, engine):
        """Object with bbox as list (not polygon)."""

        class MockLine:
            text = "Test"
            score = 0.75
            # bbox as a list in [x1,y1,x2,y2] format - treated as polygon by _polygon_to_bbox
            bbox = (10, 20, 110, 70)

        result = engine._parse_ocr_line(MockLine())
        assert result is not None
        text, confidence, bbox = result
        assert text == "Test"
        # bbox is treated as polygon (tuple of points), returns None since (10,20,110,70) is not [[x,y],...]
        assert bbox is None

    def test_returns_none_when_object_missing_attributes(self, engine):

        class MockLine:
            pass

        assert engine._parse_ocr_line(MockLine()) is None

    def test_returns_none_when_text_missing(self, engine):

        class MockLine:
            score = 0.5
            polygon = [[0, 0], [100, 0], [100, 50], [0, 50]]

        assert engine._parse_ocr_line(MockLine()) is None

    def test_returns_none_when_score_missing(self, engine):

        class MockLine:
            text = "Hello"
            polygon = [[0, 0], [100, 0], [100, 50], [0, 50]]

        assert engine._parse_ocr_line(MockLine()) is None


class TestPaddleOcrEngineExtract:
    """Tests for PaddleOCREngine.extract() method.

    Uses a fully mocked engine via fixture so we don't need paddleocr installed.
    """

    @pytest.fixture
    def engine(self):
        """Create engine with a MagicMock _engine that returns configurable OCR data."""
        eng = object.__new__(PaddleOCREngine)
        eng._engine = MagicMock()
        return eng

    def test_returns_empty_result_for_none_raw(self, engine):
        """When PaddleOCR returns None, should return empty OCRResult."""
        engine._engine.ocr.return_value = None
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == ""
        assert result.confidence is None
        assert result.blocks == []

    def test_returns_empty_result_for_non_list_raw(self, engine):
        engine._engine.ocr.return_value = "unexpected string"
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == ""
        assert result.blocks == []

    def test_handles_page_with_none_lines(self, engine):
        engine._engine.ocr.return_value = [[None]]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == ""
        assert result.blocks == []

    def test_handles_page_with_non_list_lines(self, engine):
        engine._engine.ocr.return_value = [["not a line"]]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == ""
        assert result.blocks == []

    def test_extracts_single_line(self, engine):
        # Single page with single line: ocr returns list of pages, each page has lines
        # Structure: [page [line [polygon, [text, conf]]]]
        engine._engine.ocr.return_value = [
            [
                [[[0, 0], [100, 0], [100, 50], [0, 50]], ["Hello", 0.92]]
            ]
        ]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == "Hello"
        assert result.confidence == 0.92
        assert len(result.blocks) == 1
        assert result.blocks[0].text == "Hello"

    def test_extracts_multiple_lines(self, engine):
        engine._engine.ocr.return_value = [
            [
                [[[0, 0], [100, 0], [100, 20], [0, 20]], ["Line 1", 0.90]],
                [[[0, 20], [100, 20], [100, 40], [0, 40]], ["Line 2", 0.85]],
            ]
        ]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == "Line 1\nLine 2"
        assert result.confidence == pytest.approx(0.875)
        assert len(result.blocks) == 2

    def test_extracts_multiple_pages(self, engine):
        engine._engine.ocr.return_value = [
            [[[[0, 0], [100, 0], [100, 20], [0, 20]], ["Page 1", 0.90]]],
            [[[[0, 0], [100, 0], [100, 20], [0, 20]], ["Page 2", 0.88]]],
        ]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == "Page 1\nPage 2"
        assert result.confidence == pytest.approx(0.89)
        assert len(result.blocks) == 2

    def test_skips_lines_with_parse_failure(self, engine):
        engine._engine.ocr.return_value = [
            [
                [[[0, 0], [100, 0], [100, 20], [0, 20]], ["Valid", 0.90]],
                "invalid line",
                [[[0, 20], [100, 20], [100, 40], [0, 40]], ["Also Valid", 0.85]],
            ]
        ]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == "Valid\nAlso Valid"
        assert len(result.blocks) == 2

    def test_confidence_is_none_when_no_blocks(self, engine):
        engine._engine.ocr.return_value = [[]]
        result = engine.extract(Path("/fake/image.png"))
        assert result.text == ""
        assert result.confidence is None

    def test_skips_blocks_with_empty_text(self, engine):
        # Empty text blocks are still added to result.blocks, but filtered from result.text
        engine._engine.ocr.return_value = [
            [
                [[[0, 0], [100, 0], [100, 20], [0, 20]], ["", 0.90]],
                [[[0, 20], [100, 20], [100, 40], [0, 40]], ["Valid", 0.85]],
            ]
        ]
        result = engine.extract(Path("/fake/image.png"))
        # Empty text is filtered from the joined text, but the block is still in blocks list
        assert result.text == "Valid"
        # Both blocks exist - empty text block is NOT filtered from blocks list
        assert len(result.blocks) == 2
        assert result.blocks[0].text == ""
        assert result.blocks[1].text == "Valid"
