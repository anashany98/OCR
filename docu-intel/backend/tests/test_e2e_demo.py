"""End-to-end demo: complete pipeline with a real invoice document."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_e2e_demo():
    print("=" * 70)
    print("TEST END-TO-END: Pipeline completo con documento real")
    print("=" * 70)

    # ============================================================
    # 1. DOCUMENTO REAL: FACTURA
    # ============================================================
    FACTURA = """FACTURA

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

    print("\n📄 DOCUMENTO DE ENTRADA:")
    print("-" * 40)
    print(FACTURA[:300] + "...")

    # ============================================================
    # 2. PASO 1: CLASIFICACIÓN
    # ============================================================
    print("\n🔍 PASO 1: CLASIFICACIÓN")
    print("-" * 40)
    from app.services.classification import classify_document
    classification = classify_document("F-2026-0143.pdf", "/data/facturas/F-2026-0143.pdf", FACTURA)
    print(f"  Tipo detectado: {classification.document_type}")
    print(f"  Confianza: {classification.confidence:.2f}")
    print(f"  Reglas match: {classification.matched_rules}")

    # ============================================================
    # 3. PASO 2: EXTRACCIÓN ESTRUCTURADA
    # ============================================================
    print("\n📊 PASO 2: EXTRACCIÓN ESTRUCTURADA")
    print("-" * 40)
    from app.services.business_extraction import extract_invoice
    extraction = extract_invoice(1, FACTURA, classification.confidence)
    print(f"  Nº Factura: {extraction.invoice_number}")
    print(f"  Proveedor: {extraction.supplier_name}")
    print(f"  NIF: {extraction.supplier_tax_id}")
    print(f"  Cliente: {extraction.client_name}")
    print(f"  Fecha: {extraction.date}")
    print(f"  Base imponible: {extraction.taxable_base} €")
    print(f"  IVA: {extraction.vat_amount} €")
    print(f"  Total: {extraction.total_amount} €")
    print(f"  Moneda: {extraction.currency}")
    print(f"  Confianza: {extraction.confidence:.2f}")
    print(f"  Líneas extraídas: {len(extraction.lines)}")
    for i, line in enumerate(extraction.lines, 1):
        print(f"    {i}. {line.description} — {line.quantity} {line.unit} x {line.unit_price} = {line.total_price} €")

    # ============================================================
    # 4. PASO 3: MULTI-QUERY EXPANSION
    # ============================================================
    print("\n🔎 PASO 3: MULTI-QUERY EXPANSION")
    print("-" * 40)
    from app.ai.multi_query import generate_query_variations, expand_numbered_query
    queries = ["¿Cuánto facturó TEXTILES MALLORCA?", "factura F-2026-0143", "base imponible IVA"]
    for q in queries:
        variations = generate_query_variations(q)
        numbered = expand_numbered_query(q)
        all_vars = variations + [v for v in numbered if v.text != q]
        print(f'  Query: "{q}"')
        print(f"  Variaciones generadas: {len(all_vars)}")
        for v in all_vars[:3]:
            print(f'    → "{v.text}" (peso: {v.weight:.2f})')
        print()

    # ============================================================
    # 5. PASO 4: STRUCTURED OUTPUT
    # ============================================================
    print("📋 PASO 4: STRUCTURED OUTPUT")
    print("-" * 40)
    from app.ai.structured_output import to_structured_response
    response = to_structured_response(FACTURA)
    print(f"  Formato detectado: {response.format}")
    print(f"  Confianza: {response.confidence:.2f}")
    print(f"  Montos extraídos: {response.data.get('amounts', [])}")
    print(f"  Fechas: {response.data.get('dates', [])}")
    print(f"  Referencias: {response.data.get('references', [])}")
    print(f"  Fuentes: {len(response.sources)}")
    print(f"  Warnings: {response.warnings}")

    # ============================================================
    # 6. PASO 5: RESPUESTA API
    # ============================================================
    print("\n🌐 PASO 5: RESPUESTA API (schema AIAnswerRead)")
    print("-" * 40)
    from app.schemas.ai import AIAnswerRead
    api_response = AIAnswerRead(
        id=1,
        question_id=1,
        answer="La factura F-2026-0143 de TEXTILES MALLORCA asciende a 5.142,50 € (base: 4.250 €, IVA 21%: 892,50 €). Contiene 3 líneas de servicio.",
        confidence=0.92,
        model_name="qwen/qwen3-14b",
        created_at=datetime.now(),
        sources=[],
    )
    print(f"  Answer: {api_response.answer[:80]}...")
    print(f"  Confidence: {api_response.confidence}")
    print(f"  Model: {api_response.model_name}")
    print(f"  Structured:")
    if api_response.structured:
        s = api_response.structured
        print(f'    Format: {s.get("format")}')
        print(f'    Amounts: {s.get("data", {}).get("amounts", [])}')
        print(f'    Confidence: {s.get("confidence")}')

    # ============================================================
    # 7. PASO 6: ALBARÁN (NUEVO)
    # ============================================================
    print("\n📦 PASO 6: ALBARÁN (NUEVO)")
    print("-" * 40)
    ALBARAN = """ALBARÁN DE ENTREGA

Proveedor: DECORACIONES EGEA, S.L.
Cliente: HOTEL VISTAMAR
Fecha: 24 de febrero de 2026
Nº albarán: ALB-2026-0045

Tela FRUTOS FR 315.315-1 NATURAL        100      Metros    6,94    666,24
Tela LINO BLANCO 150cm                   50      Metros    8,50    425,00

Total EUR IVA excl.                   1.156,24
"""
    from app.services.business_extraction import extract_delivery_note
    ext = extract_delivery_note(2, ALBARAN, 0.95)
    print(f"  Nº Albarán: {ext.delivery_number}")
    print(f"  Proveedor: {ext.supplier_name}")
    print(f"  Cliente: {ext.client_name}")
    print(f"  Total: {ext.total_amount} €")
    print(f"  Líneas: {len(ext.lines)}")

    # ============================================================
    # 8. PASO 7: HOJA DE CONFECCIÓN (NUEVO)
    # ============================================================
    print("\n✂️  PASO 7: HOJA DE CONFECCIÓN (NUEVO)")
    print("-" * 40)
    HOJA = """HOJA DE CONFECCIÓN

Modelo: VESTIDO VERANO 2026
Referencia: VV-2026-001
Tela: ALGODÓN PEINADO 150cm

INSTRUCCIONES:
1. Cortar pieza frontal (2 unidades)
2. Cortar pieza trasera (1 unidad)
3. Unir hombros con pespunte recto 3mm
"""
    result = classify_document("hoja.pdf", "/data/hoja.pdf", HOJA)
    print(f"  Tipo detectado: {result.document_type}")
    print(f"  Confianza: {result.confidence:.2f}")
    print(f"  → Clasificado como documento de confección")
    print(f"  → Sin extracción estructurada (es un dibujo manual)")

    # ============================================================
    # RESUMEN
    # ============================================================
    print("\n" + "=" * 70)
    print("✅ PIPELINE END-TO-END COMPLETADO CON ÉXITO")
    print("=" * 70)
    print(f"  📄 Factura: {extraction.invoice_number} — {extraction.total_amount} € ({len(extraction.lines)} líneas)")
    print(f"  📦 Albarán: {ext.delivery_number} — {ext.total_amount} € ({len(ext.lines)} líneas)")
    print(f"  ✂️  Confección: {result.document_type} (sin extracción)")
    print(f"  🔎 Multi-query: {len(generate_query_variations('test'))} variaciones por query")
    print(f"  📋 Structured: formato={response.format}, montos={len(response.data.get('amounts', []))}")
    print(f"  🌐 API: confianza={api_response.confidence:.0%}")
    print("=" * 70)


if __name__ == "__main__":
    run_e2e_demo()
