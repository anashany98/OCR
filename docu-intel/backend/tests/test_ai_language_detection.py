from app.ai.agent import _question_is_spanish, _response_looks_spanish


def test_response_language_detection_accepts_spanish_without_accents():
    answer = (
        "Segun el documento de presupuesto, el proveedor indica un importe total "
        "y no he encontrado datos adicionales fuera del contexto disponible."
    )

    assert _response_looks_spanish(answer) is True


def test_response_language_detection_rejects_english_answer():
    answer = (
        "According to the retrieved document, the supplier indicates a total amount "
        "and there is no additional evidence in the available context."
    )

    assert _response_looks_spanish(answer) is False


def test_question_language_detection_uses_detector_and_fallbacks():
    assert _question_is_spanish("Cuanto mide el salon del plano segun el documento?") is True
    assert _question_is_spanish("What is the total amount in the invoice?") is False
