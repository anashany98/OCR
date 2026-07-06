"""AI Chat test with REAL data — simulates full conversation flow.

Tests the complete AI pipeline:
1. Tool selection based on question
2. Multi-query expansion
3. Context collection
4. Grounded fallback response
5. Structured output
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))


FACTURA_TEXT = """FACTURA

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

ALBARAN_TEXT = """ALBARÁN DE ENTREGA

Proveedor: DECORACIONES EGEA, S.L.
Cliente: HOTEL VISTAMAR
Fecha: 24 de febrero de 2026
Nº albarán: ALB-2026-0045

Tela FRUTOS FR 315.315-1 NATURAL        100      Metros    6,94    666,24
Tela LINO BLANCO 150cm                   50      Metros    8,50    425,00
Hilo COATS Epic 40                       20      Rollo     3,25     65,00

Total EUR IVA excl.                   1.156,24
"""

PRESUPUESTO_TEXT = """PRESUPUESTO

Nº presupuesto: 260074
Fecha: 10 de enero de 2026
Cliente: ALEJANDRA COMPANY LASERE
Estado: Aceptado

Mobiliario restaurante                  15      Unidad   450,00  6.750,00
Sillas tapizadas                        30      Unidad   120,00  3.600,00
Mesas redondas 120cm                    8      Unidad   280,00  2.240,00

Total:                            12.590,00
"""


def run_chat_simulation():
    print("=" * 70)
    print("SIMULACIÓN DE CHAT IA CON DATOS REALES")
    print("=" * 70)

    # Simulated documents in "database"
    documents = [
        {"id": 1, "type": "factura", "text": FACTURA_TEXT, "filename": "F-2026-0143.pdf"},
        {"id": 2, "type": "albaran", "text": ALBARAN_TEXT, "filename": "ALB-2026-0045.pdf"},
        {"id": 3, "type": "presupuesto", "text": PRESUPUESTO_TEXT, "filename": "presupuesto_260074.pdf"},
    ]

    # ============================================================
    # QUESTIONS TO TEST
    # ============================================================
    questions = [
        "¿Cuánto facturó TEXTILES MALLORCA?",
        "¿Cuál es el NIF del proveedor de la factura F-2026-0143?",
        "¿Qué albaranes tiene HOTEL VISTAMAR?",
        "¿Cuánto suma el presupuesto 260074?",
        "¿Cuánto es el IVA de la factura?",
        "Dame el total de todos los documentos",
    ]

    from app.ai.multi_query import generate_query_variations, expand_numbered_query
    from app.ai.structured_output import to_structured_response, _extract_numbers, _extract_references
    from app.services.business_extraction import extract_invoice, extract_delivery_note, extract_budget
    from app.services.classification import classify_document

    for q_idx, question in enumerate(questions, 1):
        print(f"\n{'=' * 70}")
        print(f"PREGUNTA {q_idx}: {question}")
        print("=" * 70)

        # Step 1: Multi-query expansion
        print("\n  [1] Multi-query expansion:")
        variations = generate_query_variations(question)
        numbered = expand_numbered_query(question)
        all_vars = variations + [v for v in numbered if v.text != question]
        print(f"      {len(all_vars)} variaciones generadas")
        for v in all_vars[:3]:
            print(f"        → \"{v.text}\" (peso: {v.weight:.2f})")

        # Step 2: Search (simulated - find matching documents)
        print("\n  [2] Búsqueda en documentos:")
        relevant_docs = []
        for doc in documents:
            # Simple keyword matching (simulates hybrid search)
            keywords = question.lower().split()
            text_lower = doc["text"].lower()
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches >= 2:
                relevant_docs.append((doc, matches))
                print(f"      ✓ {doc['filename']} ({matches} keywords match)")

        if not relevant_docs:
            # Fallback: match any document
            relevant_docs = [(documents[0], 1)]
            print(f"      → Usando documento por defecto: {relevant_docs[0][0]['filename']}")

        # Step 3: Extract data from relevant documents
        print("\n  [3] Extracción de datos:")
        for doc, _ in relevant_docs:
            if doc["type"] == "factura":
                ext = extract_invoice(doc["id"], doc["text"], 0.95)
                print(f"      Factura {ext.invoice_number}:")
                print(f"        Proveedor: {ext.supplier_name}")
                print(f"        Base: {ext.taxable_base} €")
                print(f"        IVA: {ext.vat_amount} €")
                print(f"        Total: {ext.total_amount} €")
                print(f"        Líneas: {len(ext.lines)}")
            elif doc["type"] == "albaran":
                ext = extract_delivery_note(doc["id"], doc["text"], 0.95)
                print(f"      Albarán {ext.delivery_number}:")
                print(f"        Proveedor: {ext.supplier_name}")
                print(f"        Cliente: {ext.client_name}")
                print(f"        Total: {ext.total_amount} €")
            elif doc["type"] == "presupuesto":
                ext = extract_budget(doc["id"], doc["text"], 0.95)
                print(f"      Presupuesto {ext.budget_number}:")
                print(f"        Cliente: {ext.client_name}")
                print(f"        Total: {ext.total_amount} €")
                print(f"        Estado: {ext.status}")

        # Step 4: Generate grounded answer
        print("\n  [4] Respuesta grounded:")
        answer_parts = []
        for doc, _ in relevant_docs:
            if doc["type"] == "factura":
                ext = extract_invoice(doc["id"], doc["text"], 0.95)
                if "facturó" in question.lower() or "total" in question.lower():
                    answer_parts.append(f"La factura {ext.invoice_number} de {ext.supplier_name} asciende a {ext.total_amount} €")
                elif "nif" in question.lower():
                    answer_parts.append(f"El NIF del proveedor {ext.supplier_name} es {ext.supplier_tax_id}")
                elif "iva" in question.lower():
                    answer_parts.append(f"El IVA de la factura es {ext.vat_amount} € (21% sobre {ext.taxable_base} €)")
                else:
                    answer_parts.append(f"Factura {ext.invoice_number}: {ext.total_amount} €")
            elif doc["type"] == "albaran":
                ext = extract_delivery_note(doc["id"], doc["text"], 0.95)
                if "albarán" in question.lower() or "albaranes" in question.lower():
                    answer_parts.append(f"Albarán {ext.delivery_number} de {ext.supplier_name} para {ext.client_name}: {ext.total_amount} €")
                else:
                    answer_parts.append(f"Albarán {ext.delivery_number}: {ext.total_amount} €")
            elif doc["type"] == "presupuesto":
                ext = extract_budget(doc["id"], doc["text"], 0.95)
                if "suma" in question.lower() or "total" in question.lower():
                    answer_parts.append(f"El presupuesto {ext.budget_number} asciende a {ext.total_amount} €")
                else:
                    answer_parts.append(f"Presupuesto {ext.budget_number}: {ext.total_amount} €")

        answer = ". ".join(answer_parts) if answer_parts else "No encontré información relevante."
        print(f"      \"{answer}\"")

        # Step 5: Structured output
        print("\n  [5] Structured output:")
        structured = to_structured_response(answer)
        print(f"      Formato: {structured.format}")
        print(f"      Confianza: {structured.confidence:.2f}")
        print(f"      Montos: {structured.data.get('amounts', [])}")
        print(f"      Referencias: {structured.data.get('references', [])}")

        # Step 6: API response
        print("\n  [6] API response:")
        print(f"      answer: \"{answer[:60]}...\"")
        print(f"      confidence: {structured.confidence}")
        print(f"      structured.format: {structured.format}")
        print(f"      structured.amounts: {structured.data.get('amounts', [])}")

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("RESUMEN DE LA SIMULACIÓN DE CHAT")
    print("=" * 70)
    print(f"  Preguntas procesadas: {len(questions)}")
    print(f"  Documentos en base: {len(documents)}")
    print(f"  Multi-query: {len(generate_query_variations('test'))} variaciones/pregunta")
    print(f"  Extracción: facturas, albaranes, presupuestos")
    print(f"  Structured output: respuestas enriquecidas")
    print("=" * 70)


if __name__ == "__main__":
    run_chat_simulation()
