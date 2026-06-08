from __future__ import annotations

import asyncio

import httpx
import pytest


def test_local_ai_chat_retries_transient_server_error():
    from app.ai.local_client import LocalOpenAICompatibleClient, reset_local_ai_circuit_breakers

    reset_local_ai_circuit_breakers()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "loading"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "respuesta ok"}}]},
        )

    client = LocalOpenAICompatibleClient(
        base_url="http://ai.local/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_delay_seconds=0,
    )

    assert asyncio.run(client.chat([{"role": "user", "content": "hola"}])) == "respuesta ok"
    assert calls == 2


def test_local_ai_circuit_breaker_opens_after_consecutive_failures():
    from app.ai.local_client import (
        LocalAICircuitOpen,
        LocalOpenAICompatibleClient,
        reset_local_ai_circuit_breakers,
    )

    reset_local_ai_circuit_breakers()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": "down"})

    client = LocalOpenAICompatibleClient(
        base_url="http://ai.local/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
        max_retries=0,
        circuit_breaker_failures=2,
        circuit_breaker_reset_seconds=60,
    )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.chat([{"role": "user", "content": "hola"}]))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.chat([{"role": "user", "content": "hola"}]))
    with pytest.raises(LocalAICircuitOpen, match="temporarily unavailable"):
        asyncio.run(client.chat([{"role": "user", "content": "hola"}]))

    assert calls == 2
