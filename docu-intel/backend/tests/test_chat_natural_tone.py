"""CHAT (tanda de naturalidad) — tests del nuevo tono del chat IA.

Cubre los tres cambios principales de la reescritura del chat:

1. El system prompt pide prosa natural y NO impone el estilo telegrama
   ("Sin saludos ni relleno, conciso, directo") ni plantillas fijas.
2. ``build_grounded_response`` ya no emite blockquotes (``> ...``) ni las
   secciones rígidas "Tambien he revisado:" / "Avisos:"; cita el archivo
   dentro de la propia frase.
3. La validacion de idioma acepta respuestas cortas en español que antes
   se rechazaban por falta de señal (lo que disparaba el fallback rígido).
"""

from __future__ import annotations

from app.ai.agent import _build_ai_messages, build_grounded_response
from app.ai.context import ContextItem
from app.ai.prompts import _SYSTEM_PROMPT
from app.ai.validation import response_fabricates_documents, response_looks_spanish


# ---------------------------------------------------------------------------
# 1. System prompt — prosa natural, no telegrama
# ---------------------------------------------------------------------------


def test_system_prompt_asks_for_natural_prose():
    """El prompt debe pedir explícitamente prosa natural en frases
    completas, no respuestas telegráficas."""
    lowered = _SYSTEM_PROMPT.lower()
    assert "prosa" in lowered
    assert "frases completas" in lowered


def test_system_prompt_drops_the_old_telegraphic_style():
    """La orden vieja 'conciso, directo, sin saludos ni relleno'
    producia respuestas robóticas; debe haber desaparecido."""
    assert "Sin saludos ni relleno" not in _SYSTEM_PROMPT
    # La mención a la plantilla fija sigue presente (ahora como prohibición),
    # pero la orden de ser 'conciso' ya no rige el estilo.
    assert "conciso, directo. Sin saludos ni relleno" not in _SYSTEM_PROMPT


def test_user_prompt_asks_for_natural_prose_when_there_is_context():
    messages = _build_ai_messages(
        "Cual es el total?",
        "Fuente 1: Texto=Total 120 EUR",
        "Sin advertencias previas.",
    )
    user = messages[1]["content"].lower()
    assert "prosa" in user
    # Cita el archivo de forma natural, no como lista aparte.
    assert "dentro de la propia frase" in user or "dentro de la frase" in user


# ---------------------------------------------------------------------------
# 2. Grounded fallback — sin blockquotes ni secciones rígidas
# ---------------------------------------------------------------------------


def _sample_item() -> ContextItem:
    return ContextItem(
        title="factura_2026_044.pdf",
        summary="Total factura 1.234,56 EUR con IVA",
        excerpt="Total factura 1.234,56 EUR con IVA",
        document_filename="factura_2026_044.pdf",
        page_number=1,
        confidence=0.92,
        ocr_confidence=0.92,
    )


def test_grounded_response_has_no_blockquote():
    """El fallback ya no envuelve el texto citado en un blockquote ``>``."""
    response = build_grounded_response(
        question="Cual es el total?",
        context_items=[_sample_item()],
        warnings=[],
    )
    assert "\n> " not in response.answer
    assert response.answer.lstrip().startswith(">") is False


def test_grounded_response_has_no_rigid_sections():
    """No debe aparecer la sección 'Tambien he revisado:' ni el bloque
    'Avisos:' como títulos fijos."""
    items = [_sample_item()]
    items.append(
        ContextItem(
            title="albaran_001.pdf",
            summary="Entrega confirmada",
            excerpt="Entrega confirmada",
            document_filename="albaran_001.pdf",
            page_number=2,
            confidence=0.8,
            ocr_confidence=0.8,
        )
    )
    response = build_grounded_response(
        question="Cual es el total?",
        context_items=items,
        warnings=["OCR al 55%"],
    )
    assert "Tambien he revisado:" not in response.answer
    assert "Avisos:" not in response.answer


def test_grounded_response_cites_filename_inline():
    """El nombre del archivo debe aparecer dentro de la respuesta, idealmente
    citado en la propia frase (no como una lista de fuentes)."""
    response = build_grounded_response(
        question="Cual es el total?",
        context_items=[_sample_item()],
        warnings=[],
    )
    assert "factura_2026_044.pdf" in response.answer


# ---------------------------------------------------------------------------
# 3. Validación relajada — español corto aceptado
# ---------------------------------------------------------------------------


def test_short_spanish_answer_is_accepted():
    """Una respuesta corta en español sin diacríticos debe aceptarse.
    Antes se rechazaba por no llegar a 2 hints de palabras funcionales
    y caía al fallback rígido."""
    assert response_looks_spanish("El total es 120 EUR.") is True


def test_clearly_english_answer_is_still_rejected():
    """La puerta sigue rechazando respuestas claramente en otro idioma."""
    assert (
        response_looks_spanish(
            "The total amount is one hundred and twenty euros, paid in full today."
        )
        is False
    )


def test_filename_fragment_still_validated_for_amounts():
    """Las puertas de importes/doc-numbers siguen estrictas: un importe
    que no está en el contexto sigue rechazándose (no se ha relajado)."""
    item = _sample_item()
    # 9.999,99 no aparece en el contexto → debe detectarse como fabricación.
    assert response_fabricates_documents(
        "El total es 9.999,99 EUR segun la factura.", [item]
    ) is True
