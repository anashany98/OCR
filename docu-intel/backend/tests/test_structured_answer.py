from app.ai.context import ContextItem
from app.ai.structured_answer import decide_structured_answer


def _amount_context(*, confidence: float | None = 0.95) -> ContextItem:
    return ContextItem(
        title="[Estructurado] Presupuesto",
        summary="Presupuesto - 1234.00 EUR - total confirmado",
        document_id=42,
        document_filename="PRESUPUESTO_42.pdf",
        page_number=1,
        confidence=confidence,
    )


def test_answers_trusted_amount_without_model():
    decision = decide_structured_answer(
        "Cual es el importe total?", [_amount_context()], can_view_prices=True
    )

    assert decision is not None
    assert decision.document_id == 42
    assert "1234.00 EUR" in decision.answer
    assert "PRESUPUESTO_42.pdf" in decision.answer


def test_never_exposes_amount_without_price_permission():
    assert (
        decide_structured_answer(
            "Cual es el importe?", [_amount_context()], can_view_prices=False
        )
        is None
    )


def test_low_confidence_evidence_stays_on_grounded_path():
    assert (
        decide_structured_answer(
            "Cual es el importe?", [_amount_context(confidence=0.69)], can_view_prices=True
        )
        is None
    )


def test_non_amount_question_does_not_short_circuit():
    assert (
        decide_structured_answer(
            "Quien es el proveedor?", [_amount_context()], can_view_prices=True
        )
        is None
    )


def test_supplier_answer_does_not_require_price_permission():
    item = ContextItem(
        title="Pedido 7",
        summary="Pedido 7 - Proveedor Maderas SL - Cliente Obra Norte - 100.00 EUR",
        document_id=7,
        document_filename="PEDIDO_7.pdf",
        confidence=0.95,
    )

    decision = decide_structured_answer("Quien es el proveedor?", [item], can_view_prices=False)

    assert decision is not None
    assert "Maderas SL" in decision.answer


def test_status_answer_keeps_source():
    item = ContextItem(
        title="Presupuesto 7",
        summary="Presupuesto 7 - Cliente Obra Norte - 100.00 EUR - Estado aceptado",
        document_id=7,
        document_filename="PRESUPUESTO_7.pdf",
        confidence=0.95,
    )

    decision = decide_structured_answer("Cual es el estado?", [item], can_view_prices=True)

    assert decision is not None
    assert "aceptado" in decision.answer
    assert "PRESUPUESTO_7.pdf" in decision.answer


def test_answers_each_delivery_note_number_and_type_from_explicit_evidence():
    item = ContextItem(
        title="albaran",
        summary=(
            "Albarán: 012770\nCONCEPTO: Entrega sillas hostel Anibal\n"
            "Albarán: 012769\nCONCEPTO: Recogida sillas hostel Anibal"
        ),
        document_id=161407,
        document_filename="albaran.pdf",
        confidence=0.98,
    )

    decision = decide_structured_answer(
        "Que albaranes aparecen y que tipo tienen?", [item], can_view_prices=False
    )

    assert decision is not None
    assert "012770 (entrega)" in decision.answer
    assert "012769 (recogida)" in decision.answer
    assert decision.document_id == 161407


def test_delivery_note_amount_without_total_is_explicitly_unconfirmed():
    item = ContextItem(
        title="albaran",
        summary="Albarán: 012770\nCONCEPTO: Entrega sillas hostel Anibal",
        document_id=161407,
        document_filename="albaran.pdf",
        confidence=0.98,
    )

    decision = decide_structured_answer(
        "Cual es el importe del albarán?", [item], can_view_prices=True
    )

    assert decision is not None
    assert "No puedo confirmar el importe" in decision.answer
    assert decision.document_id == 161407


def test_exact_document_amount_without_extracted_value_is_explicitly_unconfirmed():
    item = ContextItem(
        title="3987_001.pdf",
        summary="El numero '3987_001' aparece en el documento (coincidencia en: filename).",
        document_id=161404,
        document_filename="3987_001.pdf",
        confidence=0.98,
    )

    decision = decide_structured_answer(
        "Cual es el importe total del documento 3987_001?", [item], can_view_prices=True
    )

    assert decision is not None
    assert "No puedo confirmar el importe total" in decision.answer
    assert decision.document_id == 161404
