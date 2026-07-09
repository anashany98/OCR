"""Tests for FASE 2 extraction improvements: new _total_amount labels,
_parse_markdown_table quality gate, and relaxed _extract_lines."""
from __future__ import annotations

from app.services.business_extraction import _total_amount, _extract_lines


class TestTotalAmountNewLabels:
    """FASE 2.1: _total_amount should cover IMPORTE / A PAGAR / SUBTOTAL /
    SUMA / TOTAL FACTURA / pipe-table, while NOT matching sequence numbers."""

    def _amt(self, text: str) -> float | None:
        amt, _cur = _total_amount(text, "presupuesto")
        return amt

    def test_importe_total(self):
        assert self._amt("IMPORTE TOTAL 1.234,56 EUR") == 1234.56

    def test_a_pagar(self):
        assert self._amt("A PAGAR 2.500,00") == 2500.0

    def test_total_a_pagar(self):
        assert self._amt("TOTAL A PAGAR 890,50 €") == 890.5

    def test_subtotal(self):
        # \btotal\b inside "subtotal" used to miss this
        assert self._amt("SUBTOTAL 890,50 €") == 890.5

    def test_total_factura(self):
        assert self._amt("TOTAL FACTURA 15.670,30 EUR") == 15670.30

    def test_pipe_table_total(self):
        assert self._amt("| TOTAL | 1.234,56 | EUR |") == 1234.56

    def test_suma(self):
        assert self._amt("SUMA 3.456,78") == 3456.78

    def test_suma_total(self):
        assert self._amt("SUMA TOTAL 9.876,54 EUR") == 9876.54

    def test_legacy_total_presupuesto_still_works(self):
        assert self._amt("TOTAL PRESUPUESTO 1.645,60 EUR") == 1645.60

    def test_legacy_total_plain(self):
        assert self._amt("TOTAL: 1.000,00") == 1000.0

    def test_does_not_match_sequence_number(self):
        # The critical guard: "A CUENTA 50% PRESUPUESTO 253068" must NOT
        # latch onto 253068 (a budget sequence number with no separators).
        assert self._amt("A CUENTA 50% PRESUPUESTO 253068") is None

    def test_does_not_match_iva_percentage(self):
        # "IVA 21%" must not be picked up as an amount.
        assert self._amt("IVA 21% sobre base") is None


class TestExtractLinesRelaxed:
    """FASE 2.3: _extract_lines accepts rows missing optional columns."""

    def test_full_row(self):
        lines = _extract_lines("REF-001 Mesa de comedor 2 ud 150,00 300,00")
        assert len(lines) == 1
        ln = lines[0]
        assert ln.reference == "REF-001"
        assert ln.description == "Mesa de comedor"
        assert ln.quantity == 2.0
        assert ln.unit == "ud"
        assert ln.unit_price == 150.0
        assert ln.total_price == 300.0

    def test_row_without_unit_word(self):
        lines = _extract_lines("REF-002 Silla 4 25,00 100,00")
        assert len(lines) == 1
        ln = lines[0]
        assert ln.reference == "REF-002"
        assert ln.quantity == 4.0
        assert ln.unit_price == 25.0
        assert ln.total_price == 100.0
        assert ln.unit is None

    def test_row_without_unit_price(self):
        lines = _extract_lines("REF-003 Transporte 1 50,00")
        assert len(lines) == 1
        ln = lines[0]
        assert ln.quantity == 1.0
        assert ln.total_price == 50.0
        assert ln.unit_price is None

    def test_row_without_reference(self):
        lines = _extract_lines("Mano de obra 5 250,00")
        assert len(lines) == 1
        ln = lines[0]
        assert ln.quantity == 5.0
        assert ln.total_price == 250.0

    def test_rejects_non_line_text(self):
        assert _extract_lines("Cliente: Juan Garcia") == []
        assert _extract_lines("Pagina 1 de 3") == []
        assert _extract_lines("") == []


class TestParseMarkdownTableQualityGate:
    """FASE 2.2: a table block whose parsed rows have NO numeric price must
    not be returned as-is; the caller must fall through to fallbacks."""

    def test_good_table_has_prices(self):
        from app.services.business_extraction import _parse_markdown_table

        good = (
            "| ref | descripcion | cantidad | precio | total |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| A1 | Mesa | 2 | 150,00 | 300,00 |\n"
        )
        rows = _parse_markdown_table(good)
        assert len(rows) == 1
        assert rows[0].total_price == 300.0
        has_price = any(
            r.total_price is not None or r.unit_price is not None for r in rows
        )
        assert has_price is True

    def test_generic_header_table_has_no_prices(self):
        from app.services.business_extraction import _parse_markdown_table

        # The doc-252024 failure mode: PP-Structure emits generic col1/col2
        # headers; every cell collapses into description with no price.
        bad = (
            "| col1 | col2 | col3 | col4 | col5 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| HM JAIME | MUEBLE BUFFET |  |  | 1,00 |\n"
            "| Fabricacion | de mueble |  |  |  |\n"
        )
        rows = _parse_markdown_table(bad)
        has_price = any(
            r.total_price is not None or r.unit_price is not None for r in rows
        )
        # The gate checks for total_price/unit_price specifically; generic
        # tables fold cells into description, so has_price must be False.
        assert has_price is False, (
            "Generic-header table should have no numeric price fields so "
            "the caller falls through to layout-aware / regex fallback."
        )
