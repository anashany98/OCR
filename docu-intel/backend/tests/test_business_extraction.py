from app.services.business_extraction import extract_budget, extract_order


def test_extracts_basic_budget_fields_and_lines():
    text = """
    PRESUPUESTO 2026/143
    Cliente: Talleres Norte SL
    Fecha: 12/05/2026
    Estado: Aceptado

    REF-001 Encimera porcelanica 2 ud 120,50 241,00
    ABC123 Fregadero bajo encimera 1 ud 89,90 89,90

    Total presupuesto: 330,90 EUR
    """

    result = extract_budget(document_id=7, text=text, document_confidence=0.91)

    assert result is not None
    assert result.budget_number == "2026/143"
    assert result.client_name == "Talleres Norte SL"
    assert result.date.isoformat() == "2026-05-12"
    assert result.total_amount == 330.90
    assert result.currency == "EUR"
    assert result.status == "aceptado"
    assert result.accepted_detected is True
    assert result.lines[0].reference == "REF-001"
    assert result.lines[0].quantity == 2
    assert result.lines[1].reference == "ABC123"


def test_extracts_basic_order_fields_and_related_budget_number():
    text = """
    Pedido 2026/154
    Proveedor: Herrajes Centro
    Cliente: Talleres Norte SL
    Fecha pedido: 14-05-2026
    Presupuesto relacionado: 2026/143

    REF-001 Encimera porcelanica 2 ud 120,50 241,00

    Total pedido: 241,00 €
    """

    result = extract_order(document_id=8, text=text, document_confidence=0.88)

    assert result is not None
    assert result.order_number == "2026/154"
    assert result.supplier_name == "Herrajes Centro"
    assert result.client_name == "Talleres Norte SL"
    assert result.date.isoformat() == "2026-05-14"
    assert result.total_amount == 241.00
    assert result.currency == "EUR"
    assert result.related_budget_number == "2026/143"
    assert result.lines[0].reference == "REF-001"

