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
