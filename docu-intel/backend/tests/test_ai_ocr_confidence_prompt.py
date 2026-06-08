from __future__ import annotations

from app.ai import agent
from app.ai.agent import ContextItem, _build_ai_messages, build_grounded_response


def test_context_text_marks_low_ocr_sources_for_llm():
    item = ContextItem(
        title="factura_movil.pdf",
        summary="Total factura 120 euros",
        document_filename="factura_movil.pdf",
        page_number=1,
        confidence=0.52,
        ocr_confidence=0.52,
    )

    context_text = agent._context_text_for_ai([item])
    messages = _build_ai_messages("Cual es el total?", context_text, "Sin advertencias previas.")

    assert "[OCR DUDOSO]" in context_text
    assert "Si una fuente esta marcada como [OCR DUDOSO]" in messages[0]["content"]


def test_grounded_response_warns_when_source_has_low_ocr_confidence():
    item = ContextItem(
        title="factura_movil.pdf",
        summary="Total factura 120 euros",
        excerpt="Total factura 120 euros",
        document_filename="factura_movil.pdf",
        page_number=1,
        confidence=0.52,
        ocr_confidence=0.52,
    )

    response = build_grounded_response(
        question="Cual es el total?",
        context_items=[item],
        warnings=[],
    )

    assert "OCR dudoso" in response.answer
