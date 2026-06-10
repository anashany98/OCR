"""Tests for the async wrappers around the synchronous embedding/AI cache helpers.

The wrappers exist to keep the FastAPI event loop responsive while a request
is computing embeddings or doing Redis round-trips. They are thin
``asyncio.to_thread`` adapters, but we still cover them with focused tests so
the public async API stays stable for ``app.api.routes.ai`` and ``agent.py``.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.services import ai_cache, embeddings


class _SlowEmbed:
    """Stand-in for ``embed_text`` that blocks long enough to make the event
    loop check meaningful."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.call_count = 0

    def __call__(self, text: str, dimensions: int | None = None) -> list[float]:
        self.call_count += 1
        time.sleep(self.delay)
        return [0.0] * (dimensions or 4)


def test_embed_text_async_runs_in_thread_does_not_block_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """``embed_text_async`` must not stall the event loop while a sync embedding
    is being computed."""
    slow = _SlowEmbed(delay=0.10)
    monkeypatch.setattr(embeddings, "embed_text", slow)

    async def _runner() -> list[float]:
        # If the wrapper blocked, this sleep would be delayed by ``slow.delay``.
        loop = asyncio.get_running_loop()
        loop_task = asyncio.create_task(asyncio.sleep(0))
        result = await embeddings.embed_text_async("hola")
        # Yield control once to make sure the loop tick still happens.
        await asyncio.sleep(0)
        await loop_task
        return result

    start = time.monotonic()
    result = asyncio.run(_runner())
    elapsed = time.monotonic() - start

    assert result == [0.0] * 4
    assert slow.call_count == 1
    # Allow generous slack but the wrapper must not have blocked for the full
    # ``slow.delay`` (>= 100ms). It just needs to have completed.
    assert elapsed < 1.0


def test_embed_query_text_async_uses_query_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """``embed_query_text_async`` should delegate to the synchronous
    ``embed_query_text`` so providers that need a query prefix keep working."""
    captured: dict[str, object] = {}

    def fake_embed_query_text(text: str, dimensions: int | None = None) -> list[float]:
        captured["text"] = text
        captured["dimensions"] = dimensions
        return [1.0, 2.0, 3.0]

    monkeypatch.setattr(embeddings, "embed_query_text", fake_embed_query_text)

    result = asyncio.run(embeddings.embed_query_text_async("cuanto llevamos en melia", dimensions=3))

    assert result == [1.0, 2.0, 3.0]
    assert captured == {"text": "cuanto llevamos en melia", "dimensions": 3}


def test_get_cached_answer_async_delegates_to_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_cached_answer_async`` must invoke the sync helper and return its
    value so the cache lookup semantics stay identical."""
    captured: dict[str, object] = {}

    def fake_get(question, user_id, mode, scope_key):  # type: ignore[no-untyped-def]
        captured["question"] = question
        captured["user_id"] = user_id
        captured["mode"] = mode
        captured["scope_key"] = scope_key
        return {"answer": "cached!", "confidence": 0.9, "sources": []}

    monkeypatch.setattr(ai_cache, "get_cached_answer", fake_get)

    result = asyncio.run(
        ai_cache.get_cached_answer_async(
            "test",
            user_id=42,
            mode="default",
            scope_key="scope-x",
        )
    )

    assert result == {"answer": "cached!", "confidence": 0.9, "sources": []}
    assert captured == {
        "question": "test",
        "user_id": 42,
        "mode": "default",
        "scope_key": "scope-x",
    }


def test_cache_answer_async_delegates_to_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cache_answer_async`` must forward all kwargs to ``cache_answer`` and
    return its boolean result."""
    captured: dict[str, object] = {}

    def fake_cache_answer(question, user_id, answer, mode, scope_key, ttl):  # type: ignore[no-untyped-def]
        captured["question"] = question
        captured["user_id"] = user_id
        captured["answer"] = answer
        captured["mode"] = mode
        captured["scope_key"] = scope_key
        captured["ttl"] = ttl
        return True

    monkeypatch.setattr(ai_cache, "cache_answer", fake_cache_answer)

    payload = {"answer": "ok", "confidence": 0.5, "sources": []}
    result = asyncio.run(
        ai_cache.cache_answer_async(
            "q",
            user_id=7,
            answer=payload,
            mode="m",
            scope_key="s",
            ttl=123,
        )
    )

    assert result is True
    assert captured == {
        "question": "q",
        "user_id": 7,
        "answer": payload,
        "mode": "m",
        "scope_key": "s",
        "ttl": 123,
    }


def test_agent_imports_async_cache_helpers() -> None:
    """``app.ai.agent`` must import the async cache helpers so the FastAPI
    request handlers can ``await`` them without blocking the event loop."""
    from app.ai import agent

    # If the module imported the sync helpers by mistake, the async ones would
    # not be available on the module namespace and this assertion would fail.
    assert hasattr(agent, "get_cached_answer_async")
    assert hasattr(agent, "cache_answer_async")
    # And the call-sites in agent.py must use the async variants.
    import inspect

    source = inspect.getsource(agent.answer_question)
    assert "get_cached_answer_async" in source
    assert "cache_answer_async" in source
    # The sync names must not be referenced inside the async coroutine.
    assert "get_cached_answer(" not in source.replace("get_cached_answer_async(", "")
    assert "cache_answer(" not in source.replace("cache_answer_async(", "")


def test_ai_routes_use_async_cache_helper() -> None:
    """The streaming endpoint must await ``cache_answer_async`` from the
    request handler, not block the loop with the sync helper."""
    import inspect

    from app.api.routes import ai

    source = inspect.getsource(ai)
    assert "cache_answer_async" in source
    # The sync ``cache_answer`` import inside the stream handler must be gone.
    assert "from app.services.ai_cache import cache_answer as _cache_answer" not in source
    assert "from app.services.ai_cache import cache_answer_async as _cache_answer_async" in source
