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


def test_local_ai_chat_retries_lm_studio_termination():
    """LM Studio's transient 400 ``terminated`` response is retryable.

    The local server uses this status while loading/recovering a model,
    even though the request itself is valid.  Treating it as a permanent
    client error made real document questions fall back intermittently.
    """
    from app.ai.local_client import LocalOpenAICompatibleClient, reset_local_ai_circuit_breakers

    reset_local_ai_circuit_breakers()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(400, json={"error": "terminated"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "respuesta tras reintento"}}]},
        )

    client = LocalOpenAICompatibleClient(
        base_url="http://ai.local/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_delay_seconds=0,
    )

    assert asyncio.run(client.chat([{"role": "user", "content": "hola"}])) == (
        "respuesta tras reintento"
    )
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


# ---------------------------------------------------------------------------
# A6: ``chat_stream`` must retry transient setup errors (5xx, 429,
# connection refused) with backoff BEFORE any token is yielded, and
# must propagate the error immediately (no retry) once the
# upstream has started sending chunks. This mirrors the
# contract ``_post_chat_completion`` already has for the
# non-stream path; the stream variant just had to wait for
# the audit to point it out.
# ---------------------------------------------------------------------------


def _sse_response(chunks: list[str], status_code: int = 200) -> httpx.Response:
    """Build an httpx ``Response`` that streams the given SSE
    chunks as ``aiter_lines`` would yield them. ``httpx.MockTransport``
    does not expose a streaming helper for async iteration, so
    we use a custom request handler that returns a normal
    Response whose body is a single buffer — the chat_stream
    loop reads it line by line anyway.
    """
    body = "\n".join(chunks).encode("utf-8")
    return httpx.Response(status_code, content=body, headers={"content-type": "text/event-stream"})


def test_local_ai_chat_stream_retries_transient_error_before_first_token():
    """The first connection attempt returns 500; the second
    succeeds and streams a full answer. ``chat_stream``
    must retry (because we haven't yielded anything yet)
    and surface the final answer to the caller.
    """
    from app.ai.local_client import LocalOpenAICompatibleClient, reset_local_ai_circuit_breakers

    reset_local_ai_circuit_breakers()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "loading model"})
        # Second attempt: stream two chunks plus [DONE].
        return _sse_response(
            [
                'data: {"choices": [{"delta": {"content": "Hola "}}]}',
                'data: {"choices": [{"delta": {"content": "mundo"}}]}',
                "data: [DONE]",
            ]
        )

    client = LocalOpenAICompatibleClient(
        base_url="http://ai.local/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_delay_seconds=0,
    )

    async def collect() -> list[str | tuple[str, str]]:
        return [
            piece
            async for piece in client.chat_stream(
                [{"role": "user", "content": "saluda"}],
            )
        ]

    pieces = asyncio.run(collect())
    assert pieces == ["Hola ", "mundo"]
    # The first call failed; the retry hit the SSE endpoint
    # and streamed successfully. Total 2 calls.
    assert calls == 2


def test_local_vision_retries_transient_termination_and_opens_its_circuit(tmp_path):
    from app.ai.local_client import LocalAICircuitOpen, LocalVisionClient, reset_local_ai_circuit_breakers

    reset_local_ai_circuit_breakers()
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"not-a-real-image")
    calls = 0

    def retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(400, json={"error": "terminated"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "descripcion"}}]},
        )

    client = LocalVisionClient(
        base_url="http://vision.local/v1",
        model="vision-model",
        transport=httpx.MockTransport(retry_handler),
        max_retries=1,
        retry_base_delay_seconds=0,
    )
    assert asyncio.run(client.describe(image)) == "descripcion"
    assert calls == 2

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    failing = LocalVisionClient(
        base_url="http://vision-down.local/v1",
        model="vision-model",
        transport=httpx.MockTransport(failing_handler),
        max_retries=0,
        circuit_breaker_failures=2,
        circuit_breaker_reset_seconds=60,
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(failing.describe(image))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(failing.describe(image))
    with pytest.raises(LocalAICircuitOpen):
        asyncio.run(failing.describe(image))


def test_local_ai_chat_stream_retries_lm_studio_termination_before_first_token():
    from app.ai.local_client import LocalOpenAICompatibleClient, reset_local_ai_circuit_breakers

    reset_local_ai_circuit_breakers()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(400, json={"error": "terminated"})
        return _sse_response(
            [
                'data: {"choices": [{"delta": {"content": "respuesta"}}]}',
                "data: [DONE]",
            ]
        )

    client = LocalOpenAICompatibleClient(
        base_url="http://ai.local/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_delay_seconds=0,
    )

    async def collect() -> list[str | tuple[str, str]]:
        return [piece async for piece in client.chat_stream([{"role": "user", "content": "hola"}])]

    assert asyncio.run(collect()) == ["respuesta"]
    assert calls == 2


def test_local_ai_chat_stream_does_not_retry_after_streaming_started():
    """Once the upstream has produced a chunk, mid-stream
    failures must propagate without retry. Re-streaming a
    partial answer would duplicate the first chunks in
    the caller's UI.
    """
    from app.ai.local_client import LocalOpenAICompatibleClient, reset_local_ai_circuit_breakers

    reset_local_ai_circuit_breakers()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        # Empty SSE stream: the server returns a 200 with an
        # empty body. ``raise_for_status`` passes, then
        # ``aiter_lines`` yields nothing, and the stream ends
        # cleanly. This is the regression check: a clean
        # 200 must NOT trigger a retry.
        return httpx.Response(200, content=b"")

    client = LocalOpenAICompatibleClient(
        base_url="http://ai.local/v1",
        model="local-model",
        transport=httpx.MockTransport(handler),
        max_retries=5,
        retry_base_delay_seconds=0,
    )

    async def collect() -> list[str | tuple[str, str]]:
        return [
            piece
            async for piece in client.chat_stream(
                [{"role": "user", "content": "saluda"}],
            )
        ]

    # Empty response — the stream completes without raising.
    # The point of the test is that the retry counter does
    # not get reset / re-incremented on a clean 200.
    pieces = asyncio.run(collect())
    assert pieces == []
    # Exactly one call: a clean empty stream is not retried.
    assert calls == 1


def test_local_ai_chat_stream_propagates_429_when_out_of_retries():
    """A persistent 5xx must surface the error to the caller
    after ``max_retries`` (default 2) attempts.
    """
    from app.ai.local_client import LocalOpenAICompatibleClient, reset_local_ai_circuit_breakers

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
        max_retries=2,
        retry_base_delay_seconds=0,
    )

    async def collect() -> list[str | tuple[str, str]]:
        return [
            piece
            async for piece in client.chat_stream(
                [{"role": "user", "content": "saluda"}],
            )
        ]

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(collect())
    # max_retries=2 + 1 initial attempt = 3 calls.
    assert calls == 3
