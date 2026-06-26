from __future__ import annotations

import base64

import httpx
import pytest

from app.ocr.dots_mocr import (
    DotsMOCRConfig,
    DotsMOCREngine,
    reset_dots_mocr_breaker,
)
from app.services.circuit_breaker import (
    STATE_CLOSED,
    STATE_OPEN,
    CircuitBreaker,
    CircuitBreakerOpen,
)


# ---------------------------------------------------------------------------
# Helpers shared by the retry / circuit-breaker tests below.
# ---------------------------------------------------------------------------


class _OkResponse:
    """A minimal stand-in for ``httpx.Response`` that reports 200 OK."""

    status_code = 200

    def raise_for_status(self) -> None:  # noqa: D401 - protocol-shaped helper
        return None

    def json(self) -> dict:
        return {
            "text": "Texto VLM",
            "confidence": 0.92,
            "blocks": [
                {
                    "text": "Texto VLM",
                    "confidence": 0.92,
                    "bbox": [1, 2, 30, 40],
                    "block_type": "text",
                }
            ],
        }


class _RecordingClient:
    """``httpx.Client`` double that records every call and returns a stub
    response. Tests parameterise the ``behaviour`` to simulate 5xx,
    transport errors, or success on specific attempts.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, endpoint, *, json, headers):
        self.calls += 1
        attempt = self.calls
        behaviour = self.behaviour
        if attempt in behaviour:
            kind = behaviour[attempt]
            if kind == "ok":
                return _OkResponse()
            if kind == "5xx":
                request = httpx.Request("POST", endpoint)
                response = httpx.Response(503, request=request)
                raise httpx.HTTPStatusError("server error", request=request, response=response)
            if kind == "transport":
                raise httpx.ConnectError("connection refused", request=httpx.Request("POST", endpoint))
            raise AssertionError(f"unknown behaviour kind: {kind}")
        # No behaviour registered for this attempt — default to success
        # so the retry loop exits cleanly on the next attempt.
        return _OkResponse()


def test_dots_mocr_posts_image_and_parses_blocks(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image-bytes")
    calls: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "text": "Texto VLM",
                "confidence": 0.92,
                "blocks": [
                    {
                        "text": "Texto VLM",
                        "confidence": 0.92,
                        "bbox": [1, 2, 30, 40],
                        "block_type": "text",
                    }
                ],
            }

    class _Client:
        def __init__(self, **kwargs):
            calls.append({"init": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, endpoint, *, json, headers):
            calls.append({"endpoint": endpoint, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setattr("app.ocr.dots_mocr.httpx.Client", _Client)

    engine = DotsMOCREngine(
        DotsMOCRConfig(
            enabled=True,
            endpoint="http://vlm.local/ocr",
            api_key="secret",
            timeout_seconds=3.5,
        )
    )

    result = engine.extract(image)

    assert result.engine == "dots_mocr"
    assert result.text == "Texto VLM"
    assert result.confidence == 0.92
    assert result.blocks[0].bbox == (1.0, 2.0, 30.0, 40.0)
    assert calls[0]["init"]["timeout"] == 3.5
    assert calls[1]["endpoint"] == "http://vlm.local/ocr"
    assert calls[1]["headers"] == {"Authorization": "Bearer secret"}
    assert calls[1]["json"]["image_base64"] == base64.b64encode(b"image-bytes").decode("ascii")


# ---------------------------------------------------------------------------
# A1: retry on transient 5xx / transport errors, eventually succeed.
# ---------------------------------------------------------------------------


def test_dots_mocr_retries_5xx_then_succeeds(tmp_path, monkeypatch):
    """A1: a transient 503 on the first attempt is retried; success on
    attempt 2 returns the parsed OCR result without bubbling the error.
    """
    image = tmp_path / "page.png"
    image.write_bytes(b"image-bytes")

    client = _RecordingClient(timeout=3.5)
    # attempt 1 -> 5xx; attempt 2 -> ok
    client.behaviour = {1: "5xx", 2: "ok"}

    monkeypatch.setattr("app.ocr.dots_mocr.httpx.Client", lambda **kw: client)
    # A1 also adds a backoff sleep; avoid actually sleeping in the test
    # by stubbing ``time.sleep`` (imported into the dots_mocr module).
    monkeypatch.setattr("app.ocr.dots_mocr.time.sleep", lambda _s: None)

    engine = DotsMOCREngine(
        DotsMOCRConfig(
            enabled=True,
            endpoint="http://vlm.local/ocr",
            timeout_seconds=3.5,
            max_retries=2,
            retry_base_delay_seconds=0.0,
        )
    )
    # Inject a fresh breaker so this test does not interact with the
    # process-wide singleton's failure count.
    engine._breaker = CircuitBreaker(fail_max=5, reset_timeout=30.0, name="test-dots-retry")

    result = engine.extract(image)

    assert result.text == "Texto VLM"
    assert client.calls == 2


def test_dots_mocr_retries_transport_error_then_succeeds(tmp_path, monkeypatch):
    """A1: a transport-level error (timeout / connection drop) is
    treated like a 5xx and retried.
    """
    image = tmp_path / "page.png"
    image.write_bytes(b"image-bytes")

    client = _RecordingClient(timeout=3.5)
    client.behaviour = {1: "transport", 2: "ok"}

    monkeypatch.setattr("app.ocr.dots_mocr.httpx.Client", lambda **kw: client)
    monkeypatch.setattr("app.ocr.dots_mocr.time.sleep", lambda _s: None)

    engine = DotsMOCREngine(
        DotsMOCRConfig(
            enabled=True,
            endpoint="http://vlm.local/ocr",
            timeout_seconds=3.5,
            max_retries=2,
            retry_base_delay_seconds=0.0,
        )
    )
    engine._breaker = CircuitBreaker(fail_max=5, reset_timeout=30.0, name="test-dots-transport")

    result = engine.extract(image)

    assert result.text == "Texto VLM"
    assert client.calls == 2


def test_dots_mocr_does_not_retry_4xx(tmp_path, monkeypatch):
    """A1: a 4xx is the caller's bug, not a transient failure — retrying
    would only amplify it. The error bubbles immediately.
    """
    image = tmp_path / "page.png"
    image.write_bytes(b"image-bytes")

    class _BadRequestClient(_RecordingClient):
        def post(self, endpoint, *, json, headers):  # type: ignore[override]
            self.calls += 1
            request = httpx.Request("POST", endpoint)
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    client = _BadRequestClient(timeout=3.5)
    monkeypatch.setattr("app.ocr.dots_mocr.httpx.Client", lambda **kw: client)
    monkeypatch.setattr("app.ocr.dots_mocr.time.sleep", lambda _s: None)

    engine = DotsMOCREngine(
        DotsMOCRConfig(
            enabled=True,
            endpoint="http://vlm.local/ocr",
            timeout_seconds=3.5,
            max_retries=2,
            retry_base_delay_seconds=0.0,
        )
    )
    engine._breaker = CircuitBreaker(fail_max=5, reset_timeout=30.0, name="test-dots-4xx")

    with pytest.raises(httpx.HTTPStatusError):
        engine.extract(image)

    # Exactly one attempt: no retry on 4xx.
    assert client.calls == 1


# ---------------------------------------------------------------------------
# A1: circuit breaker integration — repeated failures trip the breaker
# so subsequent calls fail fast and the cascade falls back to Tier 1-3.
# ---------------------------------------------------------------------------


def test_dots_mocr_breaker_trips_after_repeated_5xx(tmp_path, monkeypatch):
    """A1: with ``max_retries=0`` and ``fail_max=2``, two consecutive
    pages that hit a 503 trip the breaker. The third call must raise
    ``CircuitBreakerOpen`` *without* making an HTTP request.
    """
    image = tmp_path / "page.png"
    image.write_bytes(b"image-bytes")

    client = _RecordingClient(timeout=3.5)
    # All attempts return 503
    client.behaviour = {1: "5xx", 2: "5xx", 3: "5xx", 4: "5xx"}

    monkeypatch.setattr("app.ocr.dots_mocr.httpx.Client", lambda **kw: client)
    monkeypatch.setattr("app.ocr.dots_mocr.time.sleep", lambda _s: None)

    breaker = CircuitBreaker(fail_max=2, reset_timeout=60.0, name="test-dots-trip")
    engine = DotsMOCREngine(
        DotsMOCRConfig(
            enabled=True,
            endpoint="http://vlm.local/ocr",
            timeout_seconds=3.5,
            max_retries=0,
        ),
        breaker=breaker,
    )

    # First call: 1 HTTP attempt (max_retries=0), 1 breaker failure.
    with pytest.raises(httpx.HTTPStatusError):
        engine.extract(image)
    assert client.calls == 1

    # Second call: 1 more attempt, 1 more failure -> trip.
    with pytest.raises(httpx.HTTPStatusError):
        engine.extract(image)
    assert client.calls == 2
    assert breaker.state == STATE_OPEN

    # Third call: breaker is OPEN, no HTTP request.
    calls_before = client.calls
    with pytest.raises(CircuitBreakerOpen):
        engine.extract(image)
    assert client.calls == calls_before  # no extra HTTP attempt


def test_dots_mocr_reset_helper_closes_breaker():
    """A1: ``reset_dots_mocr_breaker`` exists and forces the
    process-wide breaker back to CLOSED. Operators and tests use it
    after fixing the upstream to avoid waiting for the natural reset
    timeout.
    """
    from app.ocr import dots_mocr

    breaker = dots_mocr._get_dots_mocr_breaker()
    breaker.reset()
    # Force the breaker to OPEN via the real failure path so the
    # internal state matches what a real outage would produce.
    for _ in range(breaker.fail_max):
        with pytest.raises(RuntimeError):
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert breaker.state == STATE_OPEN

    reset_dots_mocr_breaker()

    assert breaker.state == STATE_CLOSED
