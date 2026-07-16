"""Full pipeline test with REAL data — simulates end-to-end processing.

Tests the complete flow:
1. Document classification
2. OCR text extraction
3. Business extraction (factura/pedido/albarán/presupuesto)
4. Delivery note extraction (NEW)
5. Hoja de confección classification (NEW)
6. Multi-query expansion
7. Structured output generation
8. Context collection for AI queries
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "golden_ocr"


# ---------------------------------------------------------------------------
# Real OCR texts
# ---------------------------------------------------------------------------

FACTURA_REAL = """FACTURA

Nº factura: F-2026-0143
Fecha: 15 de marzo de 2026

Proveedor: TEXTILES MALLORCA, S.A.
NIF: B12345678
C/ Industrial, 45 - 07009 Palma de Mallorca

Cliente: HOTEL PLAYAVERDE
C/ Beach, 12 - 07180 Calviá

Concepto                              Cantidad   Unidad   Precio    Importe
---------------------------------------------------------------------------
Servicio confección cortinas           200      Unidad    15,00  3.000,00
Tela premium importada                  80      Metros    12,50  1.000,00
Accesorios (argollas, bastidores)       1       Lote     250,00    250,00

Base imponible                                 4.250,00
IVA 21%                                          892,50
TOTAL                                         5.142,50

Pedido relacionado: PV26-020921
"""

ALBARAN_REAL = """ALBARÁN DE ENTREGA

Proveedor: DECORACIONES EGEA, S.L.
Cliente: HOTEL VISTAMAR
Fecha: 24 de febrero de 2026
Nº albarán: ALB-2026-0045

Descripción                           Cantidad   Unidad   Precio    Importe
---------------------------------------------------------------------------
Tela FRUTOS FR 315.315-1 NATURAL        100      Metros    6,94    666,24
Tela LINO BLANCO 150cm                   50      Metros    8,50    425,00
Hilo COATS Epic 40                       20      Rollo     3,25     65,00

Total EUR IVA excl.                   1.156,24
Importe IVA (21%)                       242,81
Total EUR IVA incl.                   1.399,05
"""

PRESUPUESTO_REAL = """PRESUPUESTO

Nº presupuesto: 260074
Fecha: 10 de enero de 2026
Cliente: ALEJANDRA COMPANY LASERE
Estado: Aceptado

Descripción                           Cantidad   Unidad   Precio    Importe
---------------------------------------------------------------------------
Mobiliario restaurante                  15      Unidad   450,00  6.750,00
Sillas tapizadas                        30      Unidad   120,00  3.600,00
Mesas redondas 120cm                    8      Unidad   280,00  2.240,00

Total:                            12.590,00
"""

HOJA_CONFECCION_REAL = """HOJA DE CONFECCIÓN

Modelo: VESTIDO VERANO 2026
Referencia: VV-2026-001
Tela: ALGODÓN PEINADO 150cm

INSTRUCCIONES:
1. Cortar pieza frontal (2 unidades)
2. Cortar pieza trasera (1 unidad)
3. Unir hombros con pespunte recto 3mm
4. Coser costados
5. Dobladillo inferior 2cm
6. Plaquetas botones: 6 unidades

Medidas:
- Largo total: 95 cm
- Ancho pecho: 48 cm (talla M)
- Ancho cadera: 52 cm (talla M)

Acabado: Lavado industrial 40°C
Empaque: Individual en polipropileno
"""


# ---------------------------------------------------------------------------
# Test: Complete pipeline per document type
# ---------------------------------------------------------------------------

class TestFullPipelineFactura:
    """Complete pipeline test for invoices."""

    def test_classify(self):
        from app.services.classification import classify_document
        result = classify_document("F-2026-0143.pdf", "/data/F-2026-0143.pdf", FACTURA_REAL)
        assert result.document_type == "factura"
        assert result.confidence > 0.7

    def test_extract(self):
        from app.services.business_extraction import extract_invoice
        ext = extract_invoice(1, FACTURA_REAL, 0.95)
        assert ext is not None
        assert ext.invoice_number == "F-2026-0143"
        assert ext.supplier_name is not None
        assert ext.supplier_tax_id == "B12345678"
        assert ext.total_amount is not None
        assert ext.total_amount > 5000
        assert len(ext.lines) >= 3

    def test_structured_output(self):
        from app.ai.structured_output import to_structured_response
        resp = to_structured_response(FACTURA_REAL)
        assert resp.confidence > 0.5
        assert "amounts" in resp.data
        assert len(resp.data["amounts"]) >= 1

    def test_multi_query(self, monkeypatch):
        from app.ai.multi_query import generate_query_variations
        from app.core.config import settings

        # This is a deterministic unit contract for the template expansion;
        # do not inherit an operator's production feature flag from .env.
        monkeypatch.setattr(settings, "search_multi_query_enabled", True)
        monkeypatch.setattr(settings, "search_multi_query_max_variants", 3)

        vars = generate_query_variations("factura TEXTILES MALLORCA")
        assert len(vars) >= 2
        texts = [v.text for v in vars]
        assert "factura TEXTILES MALLORCA" in texts


class TestFullPipelineAlbaran:
    """Complete pipeline test for delivery notes."""

    def test_classify(self):
        from app.services.classification import classify_document
        result = classify_document("ALB-2026-0045.pdf", "/data/ALB-2026-0045.pdf", ALBARAN_REAL)
        assert result.document_type == "albaran"
        assert result.confidence >= 0.5

    def test_extract(self):
        from app.services.business_extraction import extract_delivery_note
        ext = extract_delivery_note(2, ALBARAN_REAL, 0.95)
        assert ext is not None
        assert ext.delivery_number == "ALB-2026-0045"
        assert ext.supplier_name is not None
        assert ext.client_name is not None
        assert ext.total_amount is not None
        assert ext.total_amount > 1000
        assert len(ext.lines) >= 3

    def test_structured_output(self):
        from app.ai.structured_output import to_structured_response
        resp = to_structured_response(ALBARAN_REAL)
        assert resp.confidence > 0.5
        assert "amounts" in resp.data


class TestFullPipelinePresupuesto:
    """Complete pipeline test for budgets."""

    def test_classify(self):
        from app.services.classification import classify_document
        result = classify_document("presupuesto_260074.pdf", "/data/presupuestos/260074.pdf", PRESUPUESTO_REAL)
        assert result.document_type == "presupuesto"
        assert result.confidence > 0.7

    def test_extract(self):
        from app.services.business_extraction import extract_budget
        ext = extract_budget(3, PRESUPUESTO_REAL, 0.95)
        assert ext is not None
        assert ext.budget_number == "260074"
        assert ext.client_name is not None
        assert ext.total_amount is not None
        assert ext.total_amount > 10000
        assert ext.status == "aceptado"
        assert len(ext.lines) >= 3


class TestFullPipelineHojaConfeccion:
    """Complete pipeline test for confection sheets."""

    def test_classify(self):
        from app.services.classification import classify_document
        result = classify_document("hoja_VV-2026-001.pdf", "/data/confeccion/VV-2026-001.pdf", HOJA_CONFECCION_REAL)
        assert result.document_type == "hoja_confeccion"
        assert result.confidence > 0.3

    def test_extraction_returns_minimal(self):
        """Hojas de confección are hand-drawn — extraction returns minimal data."""
        from app.services.business_extraction import extract_budget, extract_invoice, extract_delivery_note
        # Extraction functions are generic — they try to extract what they can
        # The key is that classification correctly identifies the document type
        budget = extract_budget(4, HOJA_CONFECCION_REAL, 0.9)
        # May extract numbers but no budget number, no client, no status
        if budget is not None:
            assert budget.budget_number is None
            assert budget.client_name is None
            assert budget.status is None


# ---------------------------------------------------------------------------
# Test: Golden fixtures (real OCR from production)
# ---------------------------------------------------------------------------

class TestGoldenPedidoPipeline:
    """Test with real pedido OCR text from production."""

    def test_classification(self):
        from app.services.classification import classify_document
        text = (FIXTURES_DIR / "pedido_venta_pv26_020921" / "page_1.txt").read_text(encoding="utf-8")
        result = classify_document("pedido_venta_pv26_020921.pdf", "/data/pedidos/pedido.pdf", text)
        assert result.document_type == "pedido"
        assert result.confidence > 0.5

    def test_extraction(self):
        from app.services.business_extraction import extract_order
        text = (FIXTURES_DIR / "pedido_venta_pv26_020921" / "page_1.txt").read_text(encoding="utf-8")
        ext = extract_order(100, text, 0.9)
        assert ext is not None
        assert ext.order_number is not None
        assert ext.total_amount is not None
        assert ext.total_amount > 0


# ---------------------------------------------------------------------------
# Test: API schema with structured output
# ---------------------------------------------------------------------------

class TestAPISchemaStructured:
    """Test that API responses include structured output."""

    def test_answer_includes_structured(self):
        from app.schemas.ai import AIAnswerRead
        from datetime import datetime

        answer = AIAnswerRead(
            id=1, question_id=1,
            answer="Total factura: 5.142,50 EUR",
            confidence=0.9, model_name="test",
            created_at=datetime.now(), sources=[],
        )
        assert answer.structured is not None
        assert "amounts" in answer.structured.get("data", {})
        assert 5142.5 in answer.structured["data"]["amounts"]

    def test_answer_with_sources(self):
        from app.schemas.ai import AIAnswerRead, AIAnswerSourceRead
        from datetime import datetime

        source = AIAnswerSourceRead(
            id=1, answer_id=1, document_id=10,
            page_number=1, block_id=None,
            relevance_score=0.95, excerpt="Total: 5.142,50 EUR",
        )
        answer = AIAnswerRead(
            id=1, question_id=1,
            answer="La factura asciende a 5.142,50 EUR",
            confidence=0.9, model_name="test",
            created_at=datetime.now(), sources=[source],
        )
        assert answer.structured is not None
        assert len(answer.structured["sources"]) >= 1
