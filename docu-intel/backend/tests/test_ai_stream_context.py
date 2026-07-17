from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request


def _test_scope():
    """A resolved server-side scope for route-level stream tests."""
    from app.services.tenant_access import AccessScope

    return AccessScope(
        principal_type="user",
        principal_id="1",
        can_view_prices=True,
        can_search_budgets=True,
    )


@pytest.mark.asyncio
async def test_ai_stream_uses_same_structured_context_path(monkeypatch):
    from app.ai.active_context import ActiveContext
    from app.ai.tools import ToolCall
    from app.api.routes import ai as route
    from app.schemas.ai import AskRequest
    from app.services import ai_cache

    captured: dict[str, object] = {}

    # This test exercises the live retrieval branch.  Answers cached by a
    # developer's local database would correctly bypass that branch, making
    # the test order- and environment-dependent.
    async def cache_miss(**_kwargs):
        return None

    monkeypatch.setattr(ai_cache, "get_cached_answer_async", cache_miss)

    monkeypatch.setattr(
        route,
        "load_active_context",
        lambda db, user, session_id: ActiveContext(current_budget_number="260009"),
    )
    monkeypatch.setattr(
        route,
        "resolve_references",
        lambda question, state: ("por cuanto esta presupuestado 260009", SimpleNamespace()),
    )
    monkeypatch.setattr(
        route,
        "select_tools_for_question",
        lambda question, active_context=None: [ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}})],
    )
    monkeypatch.setattr(
        route,
        "select_structured_tools",
        lambda question, active_context=None: [
            ToolCall("get_budget_total", {"budget_number": "260009", "budget_id": None})
        ],
    )
    monkeypatch.setattr(
        route,
        "enforce_budget_scope",
        lambda question, state, tools: SimpleNamespace(tools=tools, warnings=[]),
    )
    monkeypatch.setattr(route, "resolve_user_access_scope", lambda db, user: _test_scope())

    def fake_collect_context(db, tools, question, access_scope=None):
        captured["tools"] = tools
        captured["question"] = question
        return [], [], None

    monkeypatch.setattr(route, "collect_context", fake_collect_context)
    monkeypatch.setattr(route, "redact_context_items_for_scope", lambda items, scope: items)
    monkeypatch.setattr(
        route,
        "evaluate_gates_for_turn",
        lambda db, question, context_items, resolved_doc_id: (
            SimpleNamespace(is_blocked=False, requires_amount=False),
            None,
        ),
    )

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
        payload=AskRequest(
            question="por cuanto esta presupuestado",
            mode="hybrid",
            session_id="session-1",
        ),
        db=SimpleNamespace(),
        user=SimpleNamespace(id=1),
    )

    assert response.media_type == "text/event-stream"
    assert captured["question"] == "por cuanto esta presupuestado 260009"
    assert [tool.name for tool in captured["tools"]][:2] == [
        "get_budget_total",
        "hybrid_search",
    ]


@pytest.mark.asyncio
async def test_ai_stream_confidence_gate_blocks_unreliable_amount(monkeypatch):
    from app.ai.active_context import ActiveContext
    from app.ai import agent
    from app.ai.agent import ContextItem, StreamOutcome
    from app.ai.tools import ToolCall
    from app.api.routes import ai as route
    from app.schemas.ai import AskRequest

    called = {"stream": False}

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
                    title="Presupuesto",
                    summary="Total 120 EUR",
                    document_id=1,
                    confidence=0.42,
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
            SimpleNamespace(
                is_blocked=True,
                requires_amount=True,
                gates_open=["ocr_baja_confianza"],
            ),
            "Confianza baja; responder con cautela.",
        ),
    )
    monkeypatch.setattr(route.settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(route.settings, "ai_model", "fake-model")
    monkeypatch.setattr(route, "_build_memory_block", lambda db, user, question: "")
    monkeypatch.setattr(agent, "_suggest_followups", lambda question, doc_id, items: [])
    monkeypatch.setattr(route, "persist_context_after_answer", lambda *args, **kwargs: None)

    async def fake_stream(question, context_items, warnings, **_kwargs):
        called["stream"] = True
        yield "respuesta llm"
        yield StreamOutcome(text="respuesta llm", ok=True)

    monkeypatch.setattr(route, "_stream_local_ai_answer", fake_stream)

    class DB:
        def add(self, obj):
            obj.id = getattr(obj, "id", 1) or 1

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
        payload=AskRequest(question="por cuanto esta presupuestado", mode="hybrid"),
        db=DB(),
        user=SimpleNamespace(id=1),
    )
    body = b"".join([chunk async for chunk in response.body_iterator]).decode()

    assert called["stream"] is False
    assert "No puedo confirmar el importe" in body
    assert "backend_confidence_gate" in body


@pytest.mark.asyncio
async def test_ai_stream_without_document_context_uses_not_found_fallback(monkeypatch):
    from app.ai.active_context import ActiveContext
    from app.ai.agent import StreamOutcome
    from app.ai.tools import ToolCall
    from app.api.routes import ai as route
    from app.schemas.ai import AskRequest

    called = {"stream": False}

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
    monkeypatch.setattr(route, "collect_context", lambda db, tools, question, access_scope=None: ([], [], None))
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
        called["stream"] = True
        yield "respuesta general"
        yield StreamOutcome(text="respuesta general", ok=True)

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
        payload=AskRequest(question="ayudame a redactar un email", mode="hybrid"),
        db=DB(),
        user=SimpleNamespace(id=1),
    )
    body = b"".join([chunk async for chunk in response.body_iterator]).decode()

    assert called["stream"] is False
    assert "respuesta general" not in body
    assert '"fallback": true' in body
    assert "No he encontrado" in body


@pytest.mark.asyncio
async def test_ai_stream_memory_only_does_not_call_llm(monkeypatch):
    from app.ai.active_context import ActiveContext
    from app.ai.agent import StreamOutcome
    from app.ai.tools import ToolCall
    from app.api.routes import ai as route
    from app.schemas.ai import AskRequest

    called = {"stream": False}

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
    monkeypatch.setattr(route, "collect_context", lambda db, tools, question, access_scope=None: ([], [], None))
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
    monkeypatch.setattr(route, "_build_memory_block", lambda db, user, question: "Resumen conversacion previa")
    monkeypatch.setattr(route, "persist_context_after_answer", lambda *args, **kwargs: None)

    async def fake_stream(question, context_items, warnings, **_kwargs):
        called["stream"] = True
        yield "respuesta general"
        yield StreamOutcome(text="respuesta general", ok=True)

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
        payload=AskRequest(question="y esto?", mode="hybrid", session_id="s1"),
        db=DB(),
        user=SimpleNamespace(id=1),
    )
    body = b"".join([chunk async for chunk in response.body_iterator]).decode()

    assert called["stream"] is False
    assert "respuesta general" not in body
    assert "No he encontrado" in body
