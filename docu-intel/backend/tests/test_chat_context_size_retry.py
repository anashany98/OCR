"""CHAT — cuando el prompt supera el ``context_length`` cargado del modelo,
el servidor LLM devuelve ``400 Context size has been exceeded``.

Antes eso se trataba como fallo de servidor y ABRÍA el circuit breaker,
cascading a fallback durante ~30s. Ahora:

1. El cliente detecta el 400 "context size" y lanza
   :class:`ContextSizeExceededError` SIN tocar el circuit breaker.
2. El agente captura el error, reduce a la mitad el presupuesto de
   contexto y reintenta una vez antes de caer al fallback.
"""

from __future__ import annotations

import pytest


def test_context_size_detection_helper():
    from app.ai.local_client import _looks_like_context_size_error

    assert _looks_like_context_size_error(400, b'{"error":"Context size has been exceeded."}')
    assert _looks_like_context_size_error(400, b'{"error":"context length too long"}')
    assert _looks_like_context_size_error(400, b"maximum context length reached")
    # Unrelated 400s and non-400 statuses must NOT match.
    assert not _looks_like_context_size_error(400, b'{"error":"bad request"}')
    assert not _looks_like_context_size_error(429, b"rate limited")
    assert not _looks_like_context_size_error(500, b"server error")


def _many_items(n: int = 8) -> list:
    """Enough long context items that halving the token budget actually
    drops some of them, so the retry prompt is measurably smaller."""
    from app.ai.agent import ContextItem

    return [
        ContextItem(
            title=f"factura_{i}.pdf",
            summary=("Total factura " + ("palabra " * 200)),
            document_id=i + 1,
            confidence=0.9,
            excerpt=("Total factura " + ("palabra " * 200)),
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_stream_retries_with_smaller_budget_on_context_size_error(monkeypatch):
    from app.ai import agent
    from app.ai.agent import StreamOutcome, _stream_local_ai_answer
    from app.ai.local_client import ContextSizeExceededError
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_model", "qwen/qwen3-14b")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(settings, "ai_max_context_tokens", 6000)

    sizes = {"prompts": []}

    class _FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def chat_stream(self, messages, temperature=0.0, max_tokens=4000):
            sizes["prompts"].append(len(messages[1]["content"]))
            if len(sizes["prompts"]) == 1:
                raise ContextSizeExceededError("too big")
            yield "Resumen del documento."

    monkeypatch.setattr(agent, "LocalOpenAICompatibleClient", _FakeClient)

    outcomes = []
    async for chunk in _stream_local_ai_answer("Resume el documento", _many_items(), []):
        outcomes.append(chunk)

    assert len(sizes["prompts"]) == 2
    # The retry prompt must be measurably smaller (budget halved → fewer items).
    assert sizes["prompts"][1] < sizes["prompts"][0]
    final = outcomes[-1]
    assert isinstance(final, StreamOutcome)
    assert final.ok is True
    assert "Resumen del documento" in final.text


@pytest.mark.asyncio
async def test_one_shot_retries_with_smaller_budget_on_context_size_error(monkeypatch):
    from app.ai import agent
    from app.ai.local_answer import try_local_ai_answer as _try_local_ai_answer
    from app.ai.local_client import ContextSizeExceededError
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_model", "qwen/qwen3-14b")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(settings, "ai_max_context_tokens", 6000)

    sizes = {"prompts": []}

    class _FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def chat(self, messages, temperature=0.0, max_tokens=4000):
            sizes["prompts"].append(len(messages[1]["content"]))
            if len(sizes["prompts"]) == 1:
                raise ContextSizeExceededError("too big")
            return "Resumen del documento."

    monkeypatch.setattr("app.ai.local_client.LocalOpenAICompatibleClient", _FakeClient)

    answer = await _try_local_ai_answer(
        "Resume el documento", _many_items(), [], fallback="fallback grounded"
    )
    assert len(sizes["prompts"]) == 2
    assert sizes["prompts"][1] < sizes["prompts"][0]
    assert answer == "Resumen del documento."


def test_context_size_error_is_distinct_from_runtime_error():
    """A 400-context-size failure is a caller fault and must NOT be an
    httpx error (which would be classified as retryable/server-fault and
    trip the circuit breaker). It subclasses RuntimeError."""
    from app.ai.local_client import ContextSizeExceededError

    assert issubclass(ContextSizeExceededError, RuntimeError)
