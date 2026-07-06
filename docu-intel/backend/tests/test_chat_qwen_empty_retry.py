"""CHAT — Qwen3 con ``/no_think`` puede devolver una respuesta VACÍA
(0 tokens, ``finish_reason='stop'``) en LM Studio. El backend debe
reintentar UNA vez con thinking habilitado antes de caer al grounded
fallback, tanto en el path de streaming como en el one-shot.

Estos tests mockean ``LocalOpenAICompatibleClient.chat_stream`` / ``chat``
para simular:
- primer intento (``/no_think``) → vacío
- reintento (thinking on) → respuesta real

y verifican que el resultado final lleva la respuesta del reintento.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_stream_retries_when_qwen_returns_empty(monkeypatch):
    from app.ai import agent
    from app.ai.agent import ContextItem, StreamOutcome, _stream_local_ai_answer
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_model", "qwen/qwen3-14b")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake")

    calls = {"count": 0}

    class _FakeClient:
        async def chat_stream(self, messages, temperature=0.0, max_tokens=4000):
            calls["count"] += 1
            # First call (with /no_think) yields nothing — the Qwen3+LM Studio
            # empty-answer failure mode. Second call (thinking on) yields the
            # real answer.
            if calls["count"] == 1:
                assert "/no_think" in messages[0]["content"]
                return
            assert "/no_think" not in messages[0]["content"]
            yield "El total es 120 EUR."

    monkeypatch.setattr(agent, "LocalOpenAICompatibleClient", _FakeClient)

    outcomes = []
    async for chunk in _stream_local_ai_answer(
        "Cual es el total?",
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
    ):
        outcomes.append(chunk)

    # Two attempts happened: the empty first try + the thinking-on retry.
    assert calls["count"] == 2
    final = outcomes[-1]
    assert isinstance(final, StreamOutcome)
    assert final.ok is True
    assert "El total es 120 EUR" in final.text


@pytest.mark.asyncio
async def test_stream_falls_back_when_retry_also_empty(monkeypatch):
    """Si el reintento TAMBIEN devuelve vacío, el outcome es ok=False
    para que el endpoint caiga al grounded fallback."""
    from app.ai import agent
    from app.ai.agent import ContextItem, StreamOutcome, _stream_local_ai_answer
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_model", "qwen/qwen3-14b")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake")

    class _FakeClient:
        async def chat_stream(self, messages, temperature=0.0, max_tokens=4000):
            # Both attempts return nothing.
            return
            yield  # pragma: no cover — makes it an async generator

    monkeypatch.setattr(agent, "LocalOpenAICompatibleClient", _FakeClient)

    outcomes = []
    async for chunk in _stream_local_ai_answer(
        "Cual es el total?",
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
    ):
        outcomes.append(chunk)

    final = outcomes[-1]
    assert isinstance(final, StreamOutcome)
    assert final.ok is False


@pytest.mark.asyncio
async def test_one_shot_retries_when_qwen_returns_empty(monkeypatch):
    from app.ai import agent
    from app.ai.agent import ContextItem, _try_local_ai_answer
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_model", "qwen/qwen3-14b")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake")

    calls = {"count": 0}

    class _FakeClient:
        async def chat(self, messages, temperature=0.0):
            calls["count"] += 1
            if calls["count"] == 1:
                return ""
            return "El total es 120 EUR."

    monkeypatch.setattr(agent, "LocalOpenAICompatibleClient", _FakeClient)

    answer = await _try_local_ai_answer(
        "Cual es el total?",
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
        fallback="fallback grounded",
    )
    assert calls["count"] == 2
    assert answer == "El total es 120 EUR."


@pytest.mark.asyncio
async def test_no_retry_for_non_qwen_model(monkeypatch):
    """Un modelo no-Qwen que devuelva vacío NO dispara el reintento con
    thinking (no tiene sentido ``enable_thinking`` para otros modelos)."""
    from app.ai import agent
    from app.ai.agent import ContextItem, StreamOutcome, _stream_local_ai_answer
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_model", "llama-3.1-8b")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake")

    calls = {"count": 0}

    class _FakeClient:
        async def chat_stream(self, messages, temperature=0.0, max_tokens=4000):
            calls["count"] += 1
            return
            yield  # pragma: no cover

    monkeypatch.setattr(agent, "LocalOpenAICompatibleClient", _FakeClient)

    outcomes = []
    async for chunk in _stream_local_ai_answer(
        "Cual es el total?",
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
    ):
        outcomes.append(chunk)

    assert calls["count"] == 1  # no retry
    assert isinstance(outcomes[-1], StreamOutcome)
    assert outcomes[-1].ok is False
