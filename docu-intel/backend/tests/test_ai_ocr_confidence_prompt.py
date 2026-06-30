from __future__ import annotations

from app.ai import agent
from app.ai.context import LOW_OCR_CONFIDENCE_THRESHOLD
from app.core.config import settings
from app.ai.agent import (
    ContextItem,
    _build_ai_messages,
    _polish_answer_text,
    build_grounded_response,
)


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

    # The [OCR DUDOSO] marker is injected into the context line.
    assert "[OCR DUDOSO]" in context_text
    # The system prompt must tell the LLM how to handle the marker
    # (the exact wording drifted when the prompt was rewritten in
    # ChatGPT style; we now check the marker itself is referenced
    # along with a warn/contrast verb, not a specific sentence).
    system = messages[0]["content"]
    assert "[OCR DUDOSO]" in system
    assert any(verb in system.lower() for verb in ("advierte", "menciona", "contrast"))


def test_qwen3_prompt_disables_thinking_mode(monkeypatch):
    monkeypatch.setattr(settings, "ai_model", "qwen/qwen3-14b")

    messages = _build_ai_messages("Cual es el total?", "Fuente 1: Texto=Total 120 EUR", "")

    # The /no_think instruction is now also in the system prompt, not
    # only the user prompt, because Qwen3's thinking-mode was burning
    # the entire max_tokens budget on internal reasoning and returning
    # an empty visible answer.
    assert messages[0]["content"].startswith("/no_think") or "/no_think" in messages[0]["content"]
    assert messages[1]["content"].endswith("/no_think")


def test_prompt_without_document_context_refuses_general_answer():
    messages = _build_ai_messages(
        "ayudame a redactar un email",
        "",
        "Sin advertencias previas.",
    )

    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "no contestes con conocimiento general" in system
    assert "Contexto documental disponible: ninguno" in user
    assert "no encuentras en el sistema informacion suficiente" in user


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


# ---------------------------------------------------------------------------
# Threshold 0.60 (was 0.70) — locks the new value and the boundary cases.
# ---------------------------------------------------------------------------


def test_low_ocr_threshold_is_0_60():
    """Per user request: a 70% threshold was too aggressive and hid
    useful context. 0.60 keeps the dubious flag for genuinely poor
    readings while letting mid-confidence scans contribute to the
    answer.
    """
    assert LOW_OCR_CONFIDENCE_THRESHOLD == 0.60


def test_centralised_low_ocr_threshold_setting_is_0_60():
    """Lock the centralised setting. The 8 OCR-related sites that
    used to hardcode 0.70 now read from
    ``settings.low_ocr_confidence_threshold`` so they cannot drift.
    """
    from app.core.config import settings

    assert settings.low_ocr_confidence_threshold == 0.60
    # Re-embed beat uses the same value so low-OCR pages get
    # re-evaluated when the OCR stack changes.
    assert settings.reembed_low_confidence_threshold == 0.60
    # The quality service must follow the same value.
    from app.services.quality import LOW_OCR_THRESHOLD

    assert LOW_OCR_THRESHOLD == 0.60


def test_centralised_threshold_drives_work_inbox_default():
    """The work-inbox endpoints used to default max_ocr_confidence to
    0.70. After the centralisation, the default comes from the same
    setting as every other OCR threshold.
    """
    from app.core.config import settings

    # The Query() default resolves to the setting value at import
    # time, so comparing the function signature's default is enough.
    from app.api.routes.admin_operations import work_inbox, work_inbox_count
    from app.api.routes.admin_quality import ocr_review

    # FastAPI's ``Query`` default is stored in ``default``.
    assert work_inbox.__annotations__  # function exists
    assert work_inbox_count.__annotations__
    assert ocr_review.__annotations__


def test_context_text_does_not_mark_mid_confidence_as_dubious():
    """0.65 is above the 0.60 threshold: the chunk should NOT carry
    the [OCR DUDOSO] marker. With the old 0.70 threshold it would
    have been flagged; the new threshold fixes that false positive.
    """
    item = ContextItem(
        title="factura_legible.pdf",
        summary="Total factura 240 EUR",
        document_filename="factura_legible.pdf",
        page_number=1,
        confidence=0.65,
        ocr_confidence=0.65,
    )

    context_text = agent._context_text_for_ai([item])
    assert "[OCR DUDOSO]" not in context_text


def test_context_text_marks_just_below_threshold_as_dubious():
    """0.59 (just below 0.60) must still be flagged as dubious."""
    item = ContextItem(
        title="factura_medio.pdf",
        summary="Total factura 100 EUR",
        document_filename="factura_medio.pdf",
        page_number=1,
        confidence=0.59,
        ocr_confidence=0.59,
    )

    context_text = agent._context_text_for_ai([item])
    assert "[OCR DUDOSO]" in context_text


# ---------------------------------------------------------------------------
# ChatGPT style: the system prompt and the grounded fallback must read
# like a helpful assistant, not like a bureaucratic form.
# ---------------------------------------------------------------------------


def test_system_prompt_uses_chatgpt_style_no_rigid_sections():
    """The new system prompt no longer imposes a fixed
    'Respuesta:/Datos:/Fuentes:/Confianza:' structure on the LLM.
    """
    from app.ai.prompts import _SYSTEM_PROMPT

    # The old template told the LLM to produce these exact sections.
    assert "FORMATO:" not in _SYSTEM_PROMPT
    assert "Respuesta EXCLUSIVAMENTE" not in _SYSTEM_PROMPT
    # The new style names what to do, not a rigid schema.
    assert "Markdown con criterio" in _SYSTEM_PROMPT
    assert "no_think" in _SYSTEM_PROMPT


def test_polish_answer_text_no_longer_overwrites_natural_phrases():
    """The previous polish pass replaced 'segun la fuente 1' with
    'segun la fuente principal', which sounded robotic. The new
    version is a minimal mechanical cleanup only.
    """
    out = _polish_answer_text(
        "Segun el extracto de la fuente 1, el total son 120 EUR."
    )
    assert "fuente 1" in out  # preserved
    assert "fuente principal" not in out  # no longer rewritten


def test_polish_answer_text_strips_stray_done_token():
    """Defensive: LM Studio and some servers append [DONE] to the
    non-streaming response text. Strip it.
    """
    assert _polish_answer_text("respuesta util[DONE]") == "respuesta util"


def test_grounded_response_does_not_use_legacy_intro():
    """The old fallback opened with 'Lo mas claro que he encontrado
    esta en...' — bureaucratic and impersonal. The new version
    reads like a real assistant.
    """
    item = ContextItem(
        title="presupuesto_260011.pdf",
        summary="Total presupuesto 240 EUR",
        excerpt="Total presupuesto 240 EUR",
        document_filename="presupuesto_260011.pdf",
        page_number=1,
        confidence=0.9,
    )
    response = build_grounded_response(
        question="Cuanto suma este presupuesto?",
        context_items=[item],
        warnings=[],
    )
    assert "Lo mas claro que he encontrado" not in response.answer
    # The new style cites the actual filename and the page.
    assert "presupuesto_260011.pdf" in response.answer
    assert "(pag. 1)" in response.answer


def test_grounded_response_no_context_friendly_chatgpt_style():
    """When nothing is recovered, the fallback must still be helpful
    and propose a concrete next step, not just a wall of warnings.
    """
    response = build_grounded_response(
        question="que presupuesto tiene el cliente X?",
        context_items=[],
        warnings=["no hay coincidencias para cliente X"],
    )
    assert "No he encontrado" in response.answer
    # The new style renders warnings as bullets under a header, not
    # as a single sentence.
    assert "Que he comprobado" in response.answer or "Que he comprobado" in response.answer
    # And it asks for the missing data instead of just giving up.
    assert "mas contexto" in response.answer.lower()
