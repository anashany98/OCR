"""CHAT — los resultados de tools estructurados (get_invoice_origin_order,
get_budget_total, ...) deben leerse en español natural en el chat, sin
filtrar jerga interna como ``get_invoice_origin_order`` ni el prefijo
``[Estructurado]``, ni el patrón rígido con blockquote.

Cubre:
1. ``_render_structured_payload`` con ``found: false`` produce una frase
   natural y NO contiene el nombre interno de la tool.
2. ``build_grounded_response`` no expone ``[Estructurado]`` ni cita el
   nombre de la tool cuando el contexto principal es un item estructurado.
"""

from __future__ import annotations

from app.ai.agent import build_grounded_response
from app.ai.context import ContextItem, _structured_context_item, _render_structured_payload


# ---------------------------------------------------------------------------
# 1. not-found rendering — natural Spanish, no tool name leak
# ---------------------------------------------------------------------------


def test_invoice_origin_not_found_is_natural():
    payload = {"found": False, "invoice_number": "51094"}
    text = _render_structured_payload("get_invoice_origin_order", payload)
    assert "get_invoice_origin_order" not in text
    assert "Datos no encontrados para" not in text
    assert "pedido de origen" in text.lower()
    assert "51094" in text


def test_budget_total_not_found_is_natural():
    payload = {"found": False, "budget_number": "251094"}
    text = _render_structured_payload("get_budget_total", payload)
    assert "get_budget_total" not in text
    assert "importe total" in text.lower()
    assert "251094" in text


def test_invoiced_amount_not_found_is_natural():
    payload = {"found": False, "budget_number": "251094"}
    text = _render_structured_payload("get_invoiced_amount_for_budget", payload)
    assert "get_invoiced_amount_for_budget" not in text
    assert "facturacion" in text.lower()


def test_delivery_note_not_found_is_natural():
    payload = {"found": False}
    text = _render_structured_payload("find_delivery_note_in_scope", payload)
    assert "find_delivery_note_in_scope" not in text
    assert "albaran" in text.lower()


def test_generic_structured_not_found_never_leaks_tool_name():
    """An unknown tool must still produce a clean sentence, never the
    raw snake_case tool name."""
    payload = {"found": False, "reference": "ABC-123"}
    text = _render_structured_payload("some_unknown_tool_name", payload)
    assert "some_unknown_tool_name" not in text
    assert "no he encontrado" in text.lower()


# ---------------------------------------------------------------------------
# 2. grounded fallback does not expose [Estructurado] jargon
# ---------------------------------------------------------------------------


def test_grounded_response_with_structured_item_has_no_internal_jargon():
    """When the top context item is a structured-tool result that was
    not found, the user-facing fallback must not contain ``[Estructurado]``,
    the raw tool name, or a blockquote."""
    item = _structured_context_item(
        tool_name="get_invoice_origin_order",
        payload={"found": False, "invoice_number": "51094"},
        label="Origen factura 51094",
    )
    response = build_grounded_response(
        question="de que pedido viene la factura 51094?",
        context_items=[item],
        warnings=[],
    )
    assert "[Estructurado]" not in response.answer
    assert "get_invoice_origin_order" not in response.answer
    # No blockquote and no rigid section headers.
    assert "\n> " not in response.answer
    assert "Avisos:" not in response.answer
    # The natural not-found sentence should be present.
    assert "pedido de origen" in response.answer.lower()


def test_structured_context_item_still_carries_detection_prefix():
    """The internal ``[Estructurado]`` prefix must remain on the title
    (agent.has_answer_context matches on it), even though it is no
    longer shown to the user."""
    item = _structured_context_item(
        tool_name="get_budget_total",
        payload={"found": True, "budget_number": "1", "total_amount": 120.0, "currency": "EUR"},
        label="Total presupuesto 1",
    )
    assert item.title.startswith("[Estructurado] ")
