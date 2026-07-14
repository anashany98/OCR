"""CHAT — el endpoint /ai/ask/stream emite un evento ``delta`` POR cada
pieza incremental del LLM (streaming token-a-token), no un único delta
con todo el texto al final.

Antes el backend acumulaba todo el stream y emitía un solo ``delta`` con
el texto completo al recibir el ``StreamOutcome(ok=True)``, así que el
usuario no veía el texto escribirse en vivo (a pesar de que el frontend
ya está diseñado para incremental: ``assembled += ev.text``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request


def _test_scope():
    from app.services.tenant_access import AccessScope

    return AccessScope(
        principal_type="user",
        principal_id="1",
        can_view_prices=True,
        can_search_budgets=True,
    )


@pytest.mark.asyncio
async def test_stream_emits_one_delta_per_token(monkeypatch):
    from app.ai.active_context import ActiveContext
    from app.ai.agent import ContextItem, StreamOutcome
    from app.ai.tools import ToolCall
    from app.api.routes import ai as route
    from app.schemas.ai import AskRequest

    monkeypatch.setattr(route, "load_active_context", lambda db, user, session_id: ActiveContext())
    monkeypatch.setattr(route, "resolve_references", lambda question, state: (question, None))
    monkeypatch.setattr(
        route,
        "select_tools_for_question",
        lambda question, active_context=None: [ToolCall("hybrid_search", {"query": question, "filters": {}})],
    )
    monkeypatch.setattr(route, "select_structured_tools", lambda question, active_context=None: [])
    monkeypatch.setattr(
        route,
        "enforce_budget_scope",
        lambda question, state, tools: SimpleNamespace(tools=tools, warnings=[]),
    )
    monkeypatch.setattr(route, "resolve_user_access_scope", lambda db, user: _test_scope())
    monkeypatch.setattr(
        route,
        "collect_context",
        lambda db, tools, question, access_scope=None: (
            [
                ContextItem(
                    title="Factura",
                    summary="Total 120 EUR",
                    document_id=1,
                    confidence=0.9,
                    excerpt="Total 120 EUR",
                )
            ],
            [],
            None,
        ),
    )
    monkeypatch.setattr(route, "redact_context_items_for_scope", lambda items, scope: items)
    monkeypatch.setattr(
        route,
        "evaluate_gates_for_turn",
        lambda db, question, context_items, resolved_doc_id: (
            SimpleNamespace(is_blocked=False, requires_amount=False),
            None,
        ),
    )
    monkeypatch.setattr(route.settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(route.settings, "ai_model", "fake-model")
    monkeypatch.setattr(route, "_build_memory_block", lambda db, user, question: "")
    monkeypatch.setattr(route, "persist_context_after_answer", lambda *args, **kwargs: None)

    # The fake LLM streams the answer in 3 separate pieces. Each piece
    # must reach the client as its own ``delta`` event.
    async def fake_stream(question, context_items, warnings, **_kwargs):
        yield "El total "
        yield "es "
        yield "120 EUR."
        yield StreamOutcome(text="El total es 120 EUR.", ok=True)

    monkeypatch.setattr(route, "_stream_local_ai_answer", fake_stream)

    class DB:
        def add(self, obj):
            obj.id = getattr(obj, "id", None) or 1

        def flush(self):
            pass

        def commit(self):
            pass

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ai/ask/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )

    response = await route._build_stream_response(
        request=request,
        payload=AskRequest(question="Cual es el total?", mode="hybrid"),
        db=DB(),
        user=SimpleNamespace(id=1),
    )
    body = b"".join([chunk async for chunk in response.body_iterator]).decode()

    # Each streamed piece appears in its own delta event. There must be
    # 3 distinct ``event: delta`` lines (one per piece), not a single
    # one carrying the whole text.
    delta_count = body.count("event: delta")
    assert delta_count == 3, body
    # And the pieces arrive in order (token-by-token streaming).
    assert body.index("El total ") < body.index("es ") < body.index("120 EUR.")


@pytest.mark.asyncio
async def test_stream_falls_back_when_validation_rejects(monkeypatch):
    """Si el StreamOutcome llega con ok=False (validación rechazó la
    respuesta), el stream no debe dejar el texto parcial colgado: el
    ``end`` event envía el fallback autoritativo y el frontend lo
    reemplaza."""
    from app.ai.active_context import ActiveContext
    from app.ai.agent import ContextItem, StreamOutcome
    from app.ai.tools import ToolCall
    from app.api.routes import ai as route
    from app.schemas.ai import AskRequest

    monkeypatch.setattr(route, "load_active_context", lambda db, user, session_id: ActiveContext())
    monkeypatch.setattr(route, "resolve_references", lambda question, state: (question, None))
    monkeypatch.setattr(
        route,
        "select_tools_for_question",
        lambda question, active_context=None: [ToolCall("hybrid_search", {"query": question, "filters": {}})],
    )
    monkeypatch.setattr(route, "select_structured_tools", lambda question, active_context=None: [])
    monkeypatch.setattr(
        route,
        "enforce_budget_scope",
        lambda question, state, tools: SimpleNamespace(tools=tools, warnings=[]),
    )
    monkeypatch.setattr(route, "resolve_user_access_scope", lambda db, user: _test_scope())
    monkeypatch.setattr(
        route,
        "collect_context",
        lambda db, tools, question, access_scope=None: (
            [
                ContextItem(
                    title="Factura",
                    summary="Total 120 EUR",
                    document_id=1,
                    confidence=0.9,
                    excerpt="Total 120 EUR",
                    document_filename="factura.pdf",
                )
            ],
            [],
            None,
        ),
    )
    monkeypatch.setattr(route, "redact_context_items_for_scope", lambda items, scope: items)
    monkeypatch.setattr(
        route,
        "evaluate_gates_for_turn",
        lambda db, question, context_items, resolved_doc_id: (
            SimpleNamespace(is_blocked=False, requires_amount=False),
            None,
        ),
    )
    monkeypatch.setattr(route.settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(route.settings, "ai_model", "fake-model")
    monkeypatch.setattr(route, "_build_memory_block", lambda db, user, question: "")
    monkeypatch.setattr(route, "persist_context_after_answer", lambda *args, **kwargs: None)

    async def fake_stream(question, context_items, warnings, **_kwargs):
        yield "respuesta en otro idioma the total is"
        yield StreamOutcome(text="respuesta en otro idioma the total is", ok=False)

    monkeypatch.setattr(route, "_stream_local_ai_answer", fake_stream)

    class DB:
        def add(self, obj):
            obj.id = getattr(obj, "id", None) or 1

        def flush(self):
            pass

        def commit(self):
            pass

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ai/ask/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )

    response = await route._build_stream_response(
        request=request,
        payload=AskRequest(question="Cual es el total?", mode="hybrid"),
        db=DB(),
        user=SimpleNamespace(id=1),
    )
    body = b"".join([chunk async for chunk in response.body_iterator]).decode()

    # The partial stream was sent (token streaming still happens live)...
    assert body.count("event: delta") >= 1
    # ...but the authoritative end event marks it as a fallback and the
    # final answer is the grounded response (which mentions factura.pdf).
    assert '"fallback": true' in body
    assert "factura.pdf" in body
