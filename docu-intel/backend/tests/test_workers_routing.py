"""
Unit tests for app.workers.routing
Tests the queue routing logic based on document type and extension.
"""
from __future__ import annotations

import os
import pytest

# Must set DATABASE_URL before importing app modules that use sqlalchemy
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from app.workers.routing import HEAVY_EXTENSIONS, FAST_EXTENSIONS, HEAVY_TYPES, queue_for_document


class TestQueueForDocument:
    """Tests for queue_for_document() function."""

    def test_embeddings_job_type_returns_embeddings_queue(self):
        class MockDoc:
            extension = ".pdf"
            document_type = "plano"

        assert queue_for_document(MockDoc(), "embeddings") == "embeddings"

    def test_embeddings_with_colon_returns_embeddings_queue(self):
        class MockDoc:
            extension = ".pdf"
            document_type = "plano"

        assert queue_for_document(MockDoc(), "chunks:embeddings") == "embeddings"

    def test_pdf_returns_ocr_heavy_queue(self):
        class MockDoc:
            extension = ".pdf"
            document_type = "plano"

        assert queue_for_document(MockDoc(), "extract") == "ocr_heavy"

    def test_image_extensions_return_ocr_heavy(self):
        heavy_extensions = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"]
        for ext in heavy_extensions:
            class MockDoc:
                extension = ext
                document_type = "imagen"

            assert queue_for_document(MockDoc(), "extract") == "ocr_heavy", f"Failed for {ext}"

    def test_plano_type_returns_ocr_heavy(self):
        class MockDoc:
            extension = ".txt"
            document_type = "plano"

        assert queue_for_document(MockDoc(), "extract") == "ocr_heavy"

    def test_imagen_type_returns_ocr_heavy(self):
        class MockDoc:
            extension = ".txt"
            document_type = "imagen"

        assert queue_for_document(MockDoc(), "extract") == "ocr_heavy"

    def test_fast_extensions_return_text_fast(self):
        fast_extensions = [".txt", ".csv", ".tsv", ".log", ".eml", ".xls", ".xlsx", ".xlsm"]
        for ext in fast_extensions:
            class MockDoc:
                extension = ext
                document_type = "text"

            assert queue_for_document(MockDoc(), "extract") == "text_fast", f"Failed for {ext}"

    def test_unknown_extension_defaults_to_text_fast(self):
        class MockDoc:
            extension = ".unknown"
            document_type = "text"

        assert queue_for_document(MockDoc(), "extract") == "text_fast"

    def test_extension_case_insensitive(self):
        class MockDocUpper:
            extension = ".PDF"
            document_type = "plano"

        class MockDocLower:
            extension = ".pdf"
            document_type = "plano"

        assert queue_for_document(MockDocUpper(), "extract") == queue_for_document(MockDocLower(), "extract")

    def test_empty_extension_defaults_to_text_fast(self):
        class MockDoc:
            extension = ""
            document_type = "unknown"

        assert queue_for_document(MockDoc(), "extract") == "text_fast"


class TestRoutingConstants:
    """Tests for routing constants."""

    def test_heavy_extensions_contains_expected_types(self):
        expected = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
        assert HEAVY_EXTENSIONS == expected

    def test_fast_extensions_contains_expected_types(self):
        expected = {".txt", ".csv", ".tsv", ".log", ".eml", ".xls", ".xlsx", ".xlsm"}
        assert FAST_EXTENSIONS == expected

    def test_heavy_types(self):
        assert HEAVY_TYPES == {
            "plano",
            "imagen",
            "foto_producto",
            "muestra_tela",
            "croquis_medida",
        }