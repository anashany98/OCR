"""Tests for the agent.py refactor.

These tests verify that the refactored module split is **behaviour
preserving** for the public surface. They cover:

1. The four sub-modules (``tools``, ``context``, ``prompts``,
   ``validation``) can be imported and expose the right symbols.
2. ``agent`` re-exports the public names so legacy imports keep
   working.
3. Key pure helpers (``_normalize``, ``_extract_document_number``,
   ``_detect_language``, ``_is_aggregation_question``) keep their
   exact behaviour.
4. The orchestrator ``answer_question`` is still importable and
   its signature is unchanged.
"""
from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# 1) Sub-module imports
# ---------------------------------------------------------------------------


def test_tools_module_exposes_public_names():
    from app.ai import tools
    assert hasattr(tools, "select_tools_for_question")
    assert hasattr(tools, "ToolCall")
    # Helpers (still importable; whether they are public or private is
    # a convention, the alias ``_is_aggregation_question`` proves the
    # classifier is reachable from outside).
    assert hasattr(tools, "_is_aggregation_question")
    assert hasattr(tools, "_classify_aggregation")
    assert hasattr(tools, "_extract_document_number")
    assert hasattr(tools, "_extract_reference")
    assert hasattr(tools, "_extract_room_name")
    assert hasattr(tools, "_normalize")
    assert hasattr(tools, "_maybe_apply_relevance_filter")


def test_context_module_exposes_public_names():
    from app.ai import context
    assert hasattr(context, "ContextItem")
    assert hasattr(context, "GroundedResponse")
    assert hasattr(context, "collect_context")
    assert hasattr(context, "redact_context_items_for_scope")
    assert hasattr(context, "build_grounded_response")
    assert hasattr(context, "render_document_details")
    assert hasattr(context, "dedupe_sources")
    assert hasattr(context, "format_source")
    assert hasattr(context, "clip_excerpt")
    assert hasattr(context, "warning_lines")
    assert hasattr(context, "confidence_label")


def test_prompts_module_exposes_public_names():
    from app.ai import prompts
    assert hasattr(prompts, "build_ai_messages")
    assert hasattr(prompts, "build_context_text")
    # ``_build_ai_messages`` is the legacy alias kept for tests.
    assert hasattr(prompts, "_build_ai_messages")
    assert hasattr(prompts, "_context_line_for_ai")


def test_validation_module_exposes_public_names():
    from app.ai import validation
    assert hasattr(validation, "response_looks_spanish")
    assert hasattr(validation, "question_is_spanish")
    assert hasattr(validation, "response_fabricates_documents")
    assert hasattr(validation, "has_required_sections")
    assert hasattr(validation, "suggest_followups")
    assert hasattr(validation, "looks_like_followup")
    assert hasattr(validation, "build_memory_block")


# ---------------------------------------------------------------------------
# 2) agent.py re-exports the public surface
# ---------------------------------------------------------------------------


def test_agent_module_reexports_public_names():
    from app.ai import agent
    # The full public API of the original agent.py is still reachable.
    expected = [
        "ContextItem",
        "GroundedResponse",
        "StreamOutcome",
        "ToolCall",
        "answer_question",
        "select_tools_for_question",
        "collect_context",
        "redact_context_items_for_scope",
        "build_grounded_response",
        "render_document_details",
        "dedupe_sources",
        "format_source",
        "clip_excerpt",
        "warning_lines",
        "confidence_label",
        "build_ai_messages",
        "build_context_text",
        "response_looks_spanish",
        "question_is_spanish",
        "response_fabricates_documents",
        "has_required_sections",
        "suggest_followups",
        "looks_like_followup",
        "build_memory_block",
    ]
    for name in expected:
        assert hasattr(agent, name), f"agent.py must re-export {name}"


def test_agent_module_reexports_legacy_underscored_names():
    """Older code (and tests) imported every helper with an
    underscore prefix. The refactor must keep those names reachable
    so nothing breaks."""
    from app.ai import agent
    legacy = [
        "_context_line_for_ai",
        "_is_aggregation_question",
        "_classify_aggregation",
        "_maybe_apply_relevance_filter",
        "_extract_document_number",
        "_extract_reference",
        "_extract_filenames",
        "_extract_room_name",
        "_normalize",
        "_money_filters",
        "_dedupe_sources",
        "_build_ai_messages",
        "_context_text_for_ai",
        "_build_memory_block",
        "_question_is_spanish",
        "_response_looks_spanish",
        "_response_fabricates_documents",
        "_has_required_sections",
        "_suggest_followups",
        "_looks_like_followup",
        "_detect_language",
        "_warnings_with_low_ocr_notice",
        "_is_low_ocr_context",
        "_average_confidence",
    ]
    for name in legacy:
        assert hasattr(agent, name), f"agent.py must re-export legacy {name}"


# ---------------------------------------------------------------------------
# 3) Behaviour-preservation: pure helpers return the same results
# ---------------------------------------------------------------------------


def test_normalize_strips_accents_and_lowercases():
    from app.ai.agent import _normalize
    assert _normalize("Presupuesto ACEPTADO") == "presupuesto aceptado"
    # Idempotent: already normalised text is unchanged.
    assert _normalize("hello") == "hello"


@pytest.mark.parametrize(
    "question,expected_number",
    [
        ("dame el presupuesto 2024/154", "2024/154"),
        ("presupuesto 123456", "123456"),  # 6 digits
        ("dame el presupuesto 2024/154 y el pedido 2025/200", "2024/154"),  # first match
    ],
)
def test_extract_document_number_finds_known_patterns(question, expected_number):
    from app.ai.agent import _extract_document_number
    assert _extract_document_number(question) == expected_number


def test_extract_document_number_returns_none_for_no_number():
    from app.ai.agent import _extract_document_number
    assert _extract_document_number("hola, buenos dias") is None


def test_is_aggregation_question_true_for_money_hints():
    from app.ai.agent import _is_aggregation_question
    assert _is_aggregation_question("cuanto nos hemos gastado") is True
    assert _is_aggregation_question("total facturado en 2024") is True
    assert _is_aggregation_question("suma de pedidos") is True
    assert _is_aggregation_question("hola buenos dias") is False


def test_classify_aggregation_entity():
    from app.ai.agent import _classify_aggregation
    entity, _ = _classify_aggregation("cuanto suman los pedidos")
    assert entity == "order"
    entity, _ = _classify_aggregation("total facturado")
    assert entity == "invoice"
    entity, _ = _classify_aggregation("importe del presupuesto")
    assert entity == "budget"


def test_classify_aggregation_kind():
    from app.ai.agent import _classify_aggregation
    _, kind = _classify_aggregation("cuanto suman los pedidos")
    assert kind == "total"
    _, kind = _classify_aggregation("top 5 pedidos")
    assert kind == "top"
    # The current classifier uses a strict substring match. The
    # word "cuantos" contains "cuanto" so it is classified as
    # ``total`` rather than ``count`` — the first matching wins.
    _, kind = _classify_aggregation("cuantos pedidos hay")
    assert kind == "total"
    # A query with no aggregation hint whatsoever falls back to
    # ``count``.
    _, kind = _classify_aggregation("pedidos")
    assert kind == "count"


def test_response_fabricates_documents_detects_unknown_filename():
    from app.ai.agent import ContextItem, response_fabricates_documents
    items = [
        ContextItem(
            title="doc_real.pdf",
            summary="contenido",
            document_filename="doc_real.pdf",
        )
    ]
    assert response_fabricates_documents("segun otro_archivo.pdf hay datos", items) is True
    assert response_fabricates_documents("segun doc_real.pdf hay datos", items) is False
    # No context means no fabrication can be detected.
    assert response_fabricates_documents("segun cualquiere.pdf", []) is False


def test_dedupe_sources_drops_duplicates_and_orphan_ids():
    from app.ai.agent import ContextItem, dedupe_sources
    a = ContextItem(title="a", summary="x", document_id=1, page_number=1, block_id=1)
    b = ContextItem(title="a", summary="x", document_id=1, page_number=1, block_id=1)  # dup
    c = ContextItem(title="c", summary="z", document_id=2, page_number=1, block_id=1)
    d = ContextItem(title="d", summary="w", document_id=None)  # no doc id -> dropped
    out = dedupe_sources([a, b, c, d])
    assert [s.document_id for s in out] == [1, 2]


def test_memory_context_alone_does_not_enable_llm_answer():
    from app.ai.agent import ContextItem, has_answer_context

    items = [
        ContextItem(
            title="Memoria de la conversacion",
            summary="El usuario pregunto antes por un presupuesto.",
            relevance_score=1.0,
        )
    ]

    assert has_answer_context(items) is False


def test_format_source_includes_page_when_present():
    from app.ai.agent import ContextItem, format_source
    with_page = ContextItem(title="t", summary="", document_filename="doc.pdf", page_number=3)
    without_page = ContextItem(title="t", summary="", document_filename="doc.pdf")
    assert format_source(with_page) == "doc.pdf, pagina 3"
    assert format_source(without_page) == "doc.pdf"


def test_clip_excerpt_truncates_at_sentence_boundary():
    from app.ai.agent import clip_excerpt
    long = "Primera frase corta. Segunda frase mas larga que ayuda. Tercera frase final."
    # max_chars smaller than the whole text -> trim at the last '. ' in the window.
    clipped = clip_excerpt(long, max_chars=50)
    assert clipped.endswith("…")
    # max_chars larger than the text -> no trim.
    short = "hola mundo"
    assert clip_excerpt(short, max_chars=500) == "hola mundo"
    # Empty text -> empty string.
    assert clip_excerpt("", max_chars=100) == ""


def test_question_is_spanish_basic():
    from app.ai.agent import question_is_spanish
    # Strong Spanish signals.
    assert question_is_spanish("¿Cual es el importe del presupuesto?") is True
    # Short English with no Spanish hints.
    assert question_is_spanish("hello there friend") is False


def test_response_looks_spanish_basic():
    from app.ai.agent import response_looks_spanish
    assert response_looks_spanish("El presupuesto tiene 12 lineas y un total de 1500 euros.") is True
    assert response_looks_spanish("") is False
    assert response_looks_spanish("hello world") is False


def test_extract_filenames_finds_known_extensions():
    from app.ai.agent import _extract_filenames
    assert _extract_filenames("dame el doc presupuesto.pdf") == ["presupuesto.pdf"]
    # ``.dwg`` is not in the supported set (the extractor only knows
    # the formats the platform ingests). Verify the negative case
    # explicitly so a future extension to ``.dwg`` is easy to spot.
    assert _extract_filenames("y el plano.dwg?") == []
    assert _extract_filenames("hola sin archivos") == []


def test_extract_room_name_finds_known_rooms():
    from app.ai.agent import _extract_room_name
    assert _extract_room_name("mide el salon") == "salon"
    # 'bano' is normalised to 'bano' but returned as 'bano' too.
    assert _extract_room_name("superficie del bano") == "bano"
    # 'banio' is canonicalised to 'bano'.
    assert _extract_room_name("cuanto mide el banio") == "bano"
    assert _extract_room_name("superficie del pasillo") == "pasillo"


# ---------------------------------------------------------------------------
# 4) Orchestrator signature
# ---------------------------------------------------------------------------


def test_answer_question_signature_unchanged():
    """The orchestrator's signature is part of the public contract:
    the API route imports it by name. The refactor must not change
    the keyword arguments or their types."""
    from app.ai.agent import answer_question
    sig = inspect.signature(answer_question)
    params = list(sig.parameters)
    # db is positional, the rest are keyword-only.
    assert params[0] == "db"
    assert sig.parameters["user"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["question"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["mode"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["mode"].default is None


def test_answer_question_does_not_cap_chat_with_wait_for():
    """A6: ``answer_question`` used to wrap the non-stream
    ``client.chat()`` call in ``asyncio.wait_for(..., timeout=60)``.
    That outer cap cut the inner retry chain
    (``ai_max_retries`` + exponential backoff) short: the
    inner client had 2 retries with 0.25s / 0.5s backoff,
    i.e. up to ``0.75 + 3*120s = 360.75s`` of wall-clock, but
    the ``wait_for(60)`` killed the whole thing at 60s.

    The fix removes the outer cap so the inner timeout /
    retry chain owns the lifecycle. We assert that the
    source no longer calls ``asyncio.wait_for`` on the
    chat path (it can still call it elsewhere — e.g. on
    the streaming path which never had a cap).
    """
    from pathlib import Path

    agent_path = Path("app/ai/agent.py")
    source = agent_path.read_text(encoding="utf-8")
    # The legacy wrapper sat inside the non-stream branch
    # (the ``try: client = ...; answer = await ...`` block
    # that we tagged with the "first-load time of a 26B
    # model" comment). The new code has a comment that
    # explicitly says we removed the cap; assert that the
    # call is gone.
    assert "asyncio.wait_for(client.chat" not in source, (
        "answer_question must not wrap client.chat() in "
        "asyncio.wait_for — the inner LocalOpenAICompatibleClient "
        "already enforces a per-request timeout and a "
        "retry/backoff chain, and an outer cap cuts that "
        "chain short (audit A6)."
    )


# ---------------------------------------------------------------------------
# 5) Constants
# ---------------------------------------------------------------------------


def test_low_ocr_constants_have_expected_values():
    from app.ai.agent import LOW_OCR_CONFIDENCE_THRESHOLD, LOW_OCR_MARKER
    assert LOW_OCR_CONFIDENCE_THRESHOLD == 0.60
    assert LOW_OCR_MARKER == "[OCR DUDOSO]"


# ---------------------------------------------------------------------------
# 6) File sizes
# ---------------------------------------------------------------------------


def test_agent_module_is_under_800_lines():
    """The whole point of the refactor was to shrink ``agent.py``.
    If the orchestrator has grown back, the refactor was wasted."""
    from pathlib import Path

    # ``tests/`` is at backend/tests/, so the agent module is two
    # levels up.
    repo_root = Path(__file__).resolve().parents[1]
    agent_path = repo_root / "app" / "ai" / "agent.py"
    line_count = sum(1 for _ in agent_path.open(encoding="utf-8"))
    # The original was 1568 lines. The refactored orchestrator should
    # be well under 500. 800 leaves headroom for the CTX-2/3/4/5/6/7/8/9
    # integrations (active context, reference resolver, scope guard,
    # intent router, structured-first path, confidence gates, friendly
    # fallback, standard answer format) that the fix-grounded-chat
    # branch added on top of the existing 5-way split.
    assert line_count < 800, (
        f"agent.py grew to {line_count} lines after the CTX-2..9 "
        "integrations; the orchestrator should be under 800. "
        "If you are adding more cross-cutting code, extract a "
        "helper into one of the existing ai/ sub-modules "
        "(active_context, scope_guard, confidence_gates, etc.)."
    )
