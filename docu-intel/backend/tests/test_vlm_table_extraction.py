"""FASE 4 tests: VLM table extraction.

Tests the JSON parser, _to_float helper, and integration with the
quality gate in business_extraction.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.business_extraction import ExtractedLine, _extract_lines_for_document
from app.services.vlm_table_extraction import (
    _parse_vlm_json,
    _to_float,
    vlm_tabla_a_json,
)


# ---------------------------------------------------------------------------
# _to_float tests
# ---------------------------------------------------------------------------


class TestToFloat:
    def test_none(self):
        assert _to_float(None) is None

    def test_int(self):
        assert _to_float(42) == 42.0

    def test_float(self):
        assert _to_float(3.14) == pytest.approx(3.14)

    def test_string_int(self):
        assert _to_float("100") == 100.0

    def test_string_decimal_dot(self):
        assert _to_float("1234.56") == pytest.approx(1234.56)

    def test_string_decimal_comma(self):
        assert _to_float("1234,56") == pytest.approx(1234.56)

    def test_spanish_thousands_decimal(self):
        """1.234,56 → 1234.56"""
        assert _to_float("1.234,56") == pytest.approx(1234.56)

    def test_english_thousands(self):
        """1,234.56 → 1234.56"""
        assert _to_float("1,234.56") == pytest.approx(1234.56)

    def test_currency_stripped(self):
        assert _to_float("€1.234,56") == pytest.approx(1234.56)
        assert _to_float("$500.00") == pytest.approx(500.00)

    def test_empty_string(self):
        assert _to_float("") is None

    def test_non_numeric(self):
        assert _to_float("abc") is None


# ---------------------------------------------------------------------------
# _parse_vlm_json tests
# ---------------------------------------------------------------------------


class TestParseVlmJson:
    def test_valid_json(self):
        data = {
            "lineas": [
                {"ref": "M1", "desc": "Mueble buffet", "cant": 1, "total": 1645.60},
                {"ref": "M2", "desc": "Silla", "cant": 4, "total": 320.00},
            ],
            "total_documento": 1965.60,
        }
        lines = _parse_vlm_json(json.dumps(data))
        assert lines is not None
        assert len(lines) == 2
        assert lines[0].reference == "M1"
        assert lines[0].description == "Mueble buffet"
        assert lines[0].quantity == 1.0
        assert lines[0].total_price == pytest.approx(1645.60)

    def test_json_with_code_fences(self):
        raw = '```json\n{"lineas": [{"ref": "X1", "desc": "Test", "cant": 2, "total": 50}]}\n```'
        lines = _parse_vlm_json(raw)
        assert lines is not None
        assert len(lines) == 1
        assert lines[0].reference == "X1"

    def test_empty_lineas(self):
        data = {"lineas": [], "total_documento": None}
        lines = _parse_vlm_json(json.dumps(data))
        assert lines == []

    def test_no_numeric_prices(self):
        """Lines without prices should still be returned (VLM confidence)."""
        data = {
            "lineas": [
                {"ref": None, "desc": "Something", "cant": None, "total": None},
            ]
        }
        lines = _parse_vlm_json(json.dumps(data))
        assert lines is not None
        assert len(lines) == 1
        assert lines[0].total_price is None

    def test_invalid_json(self):
        assert _parse_vlm_json("not json at all") is None

    def test_json_embedded_in_text(self):
        raw = 'Here is the result: {"lineas": [{"desc": "Item", "total": 10}]} done.'
        lines = _parse_vlm_json(raw)
        assert lines is not None
        assert len(lines) == 1

    def test_spanish_field_names(self):
        data = {
            "lineas": [
                {
                    "referencia": "R1",
                    "descripcion": "Producto",
                    "unidades": 3,
                    "precio_unitario": 25.50,
                    "precio_total": 76.50,
                }
            ]
        }
        lines = _parse_vlm_json(json.dumps(data))
        assert lines is not None
        assert len(lines) == 1
        assert lines[0].description == "Producto"
        assert lines[0].total_price == pytest.approx(76.50)


# ---------------------------------------------------------------------------
# vlm_tabla_a_json tests (mocked HTTP)
# ---------------------------------------------------------------------------


class TestVlmTablaAJson:
    @patch("app.services.vlm_table_extraction.httpx.post")
    @patch("app.services.vlm_table_extraction.settings")
    def test_successful_extraction(self, mock_settings, mock_post, tmp_path):
        mock_settings.enable_dots_mocr = True
        mock_settings.vision_timeout_seconds = 30
        mock_settings.vision_model = "test-model"
        mock_settings.ai_base_url = "http://localhost:1234/v1"

        # Create a dummy image
        img = tmp_path / "table.png"
        img.write_bytes(b"\x89PNG\r\n")

        # Mock VLM response
        vlm_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "lineas": [
                                    {"ref": "A1", "desc": "Product", "cant": 2, "total": 100}
                                ],
                                "total_documento": 100,
                            }
                        )
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = vlm_response
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        lines = vlm_tabla_a_json(img)
        assert lines is not None
        assert len(lines) == 1
        assert lines[0].total_price == pytest.approx(100)

    @patch("app.services.vlm_table_extraction.settings")
    def test_disabled(self, mock_settings, tmp_path):
        mock_settings.enable_dots_mocr = False
        img = tmp_path / "table.png"
        img.write_bytes(b"\x89PNG\r\n")
        assert vlm_tabla_a_json(img) is None

    @patch("app.services.vlm_table_extraction.settings")
    def test_no_endpoint(self, mock_settings, tmp_path):
        mock_settings.enable_dots_mocr = True
        mock_settings.vision_model = "test"
        mock_settings.ai_base_url = ""
        img = tmp_path / "table.png"
        img.write_bytes(b"\x89PNG\r\n")
        assert vlm_tabla_a_json(img) is None


# ---------------------------------------------------------------------------
# Quality gate integration test
# ---------------------------------------------------------------------------


class TestQualityGateVlmFallback:
    def test_vlm_called_when_table_garbage(self, tmp_path):
        """When table block has no numeric prices, VLM should be tried."""
        from app.parsers.types import ExtractedBlock, ExtractedPage

        img = tmp_path / "page.png"
        img.write_bytes(b"\x89PNG\r\n")

        page = ExtractedPage(
            text="| col1 | col2 |\n| --- | --- |\n| a | b |",
            page_number=1,
            image_path=str(img),
            blocks=[
                ExtractedBlock(
                    text="| col1 | col2 |\n| --- | --- |\n| a | b |",
                    block_type="table",
                    page_number=1,
                    bbox=None,
                )
            ],
        )

        with patch(
            "app.services.business_extraction._try_vlm_table_extraction"
        ) as mock_vlm:
            mock_vlm.return_value = [
                ExtractedLine(
                    reference="A1",
                    description="Product",
                    quantity=1,
                    unit=None,
                    unit_price=None,
                    total_price=100.0,
                    confidence=0.85,
                )
            ]
            lines = _extract_lines_for_document(
                "| col1 | col2 |\n| --- | --- |\n| a | b |",
                pages=[page],
            )
            assert len(lines) == 1
            assert lines[0].total_price == 100.0
            mock_vlm.assert_called_once()
