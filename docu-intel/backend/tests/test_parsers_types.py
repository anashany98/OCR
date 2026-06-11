"""
Unit tests for app.parsers.types
Tests the ExtractedBlock, ExtractedPage, ExtractedDocument dataclasses.
"""
from __future__ import annotations

import pytest

from app.parsers.types import ExtractedBlock, ExtractedPage, ExtractedDocument


class TestExtractedBlock:
    """Tests for ExtractedBlock dataclass."""

    def test_required_fields_only(self):
        block = ExtractedBlock(block_type="text", text="Hello", page_number=1)
        assert block.block_type == "text"
        assert block.text == "Hello"
        assert block.page_number == 1
        assert block.bbox is None
        assert block.confidence is None
        assert block.source_engine is None

    def test_all_fields(self):
        block = ExtractedBlock(
            block_type="table",
            text="Row 1, Row 2",
            page_number=2,
            bbox=(10.0, 20.0, 100.0, 50.0),
            confidence=0.95,
            source_engine="paddleocr",
        )
        assert block.block_type == "table"
        assert block.text == "Row 1, Row 2"
        assert block.page_number == 2
        assert block.bbox == (10.0, 20.0, 100.0, 50.0)
        assert block.confidence == 0.95
        assert block.source_engine == "paddleocr"


class TestExtractedPage:
    """Tests for ExtractedPage dataclass."""

    def test_required_fields_only(self):
        page = ExtractedPage(page_number=1, text="Page text content")
        assert page.page_number == 1
        assert page.text == "Page text content"
        assert page.width is None
        assert page.height is None
        assert page.image_path is None
        assert page.ocr_confidence is None
        assert page.blocks == []

    def test_all_fields(self):
        blocks = [
            ExtractedBlock(block_type="text", text="Block 1", page_number=1),
            ExtractedBlock(block_type="text", text="Block 2", page_number=1),
        ]
        page = ExtractedPage(
            page_number=3,
            text="Full page text",
            width=800.0,
            height=600.0,
            image_path="/pages/page3.png",
            ocr_confidence=0.88,
            blocks=blocks,
        )
        assert page.page_number == 3
        assert page.text == "Full page text"
        assert page.width == 800.0
        assert page.height == 600.0
        assert page.image_path == "/pages/page3.png"
        assert page.ocr_confidence == 0.88
        assert len(page.blocks) == 2

    def test_default_blocks_is_empty_list(self):
        page = ExtractedPage(page_number=1, text="Text")
        assert page.blocks == []


class TestExtractedDocument:
    """Tests for ExtractedDocument dataclass."""

    def test_pages_property(self):
        pages = [
            ExtractedPage(page_number=1, text="Page 1 content"),
            ExtractedPage(page_number=2, text="Page 2 content"),
            ExtractedPage(page_number=3, text=""),
        ]
        doc = ExtractedDocument(pages=pages)
        assert len(doc.pages) == 3

    def test_text_property_joins_pages(self):
        pages = [
            ExtractedPage(page_number=1, text="First page text"),
            ExtractedPage(page_number=2, text="Second page text"),
            ExtractedPage(page_number=3, text=""),
        ]
        doc = ExtractedDocument(pages=pages)
        assert doc.text == "First page text\n\nSecond page text"

    def test_text_property_skips_empty_pages(self):
        pages = [
            ExtractedPage(page_number=1, text=""),
            ExtractedPage(page_number=2, text="Only this has content"),
            ExtractedPage(page_number=3, text=""),
        ]
        doc = ExtractedDocument(pages=pages)
        assert doc.text == "Only this has content"

    def test_text_property_empty_when_no_pages(self):
        doc = ExtractedDocument(pages=[])
        assert doc.text == ""

    def test_text_property_empty_when_all_pages_empty(self):
        pages = [
            ExtractedPage(page_number=1, text=""),
            ExtractedPage(page_number=2, text=""),
        ]
        doc = ExtractedDocument(pages=pages)
        assert doc.text == ""

    def test_single_page_document(self):
        pages = [ExtractedPage(page_number=1, text="Single page")]
        doc = ExtractedDocument(pages=pages)
        assert doc.text == "Single page"
        assert len(doc.pages) == 1