"""Thin pub/sub wrapper for OCR flow lifecycle events.

The bus is intentionally tiny: the publisher and the subscriber do not
share state (they talk through the underlying transport), so any
number of workers and any number of SSE clients can run side by side.
We never store events — a subscriber that comes online after a
publish has happened gets no replay.

The default implementation uses the **synchronous** ``redis`` client
(``redis==5.2.0`` in ``requirements.txt``), consistent with the rest
of the app. The FastAPI SSE endpoint runs the blocking
``pubsub.listen()`` in a worker thread via ``asyncio.run_in_executor``
to keep the event loop free.

The module exposes a ``Bus`` protocol plus a ``RedisBus`` default and
an ``InMemoryBus`` used by the unit tests. Tests inject an
``InMemoryBus`` via ``monkeypatch.setattr(events_bus, '_default_bus', ...)``
so the round-trip works deterministically without needing a real
Redis or fakeredis.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Protocol

import redis

from app.services.cache import cache_service


logger = logging.getLogger("app.services.events_bus")

CHANNEL = "ocr_flow"


class Bus(Protocol):
    """Minimal pub/sub interface — both Redis and in-memory buses implement it."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...
    def subscribe(
        self, channel: str = CHANNEL
    ) -> "AsyncIterator[dict[str, Any]]": ...


class InMemoryBus:
    """In-process bus used by the unit tests.

    A single ``asyncio.Queue`` is shared by all publishers and
    subscribers on the same channel. Each subscriber gets its own
    queue via ``subscribe(channel)`` so the test can assert on a
    specific consumer.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope = {"type": event_type, **payload}
        for queue in list(self._subscribers.get(CHANNEL, [])):
            await queue.put(envelope)

    def subscribe(
        self, channel: str = CHANNEL
    ) -> "AsyncIterator[dict[str, Any]]":
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(channel, []).append(queue)

        async def _iterator() -> "AsyncIterator[dict[str, Any]]":
            try:
                while True:
                    item = await queue.get()
                    if item is None:  # poison pill on cancel
                        return
                    yield item
            finally:
                if queue in self._subscribers.get(channel, []):
                    self._subscribers[channel].remove(queue)

        return _iterator()


class RedisBus:
    """Production bus backed by the shared Redis client.

    The synchronous ``pubsub.listen()`` runs in a worker thread so the
    FastAPI event loop stays responsive. Subscribers can be cancelled
    by closing the queue; the worker thread exits on the next message
    or on the next ``cancel`` poll.
    """

    def __init__(self) -> None:
        self._client: redis.Redis = cache_service.client

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope = {"type": event_type, **payload}
        try:
            # ``decode_responses=True`` is configured on the shared
            # client, so the payload is published as ``str``.
            self._client.publish(CHANNEL, json.dumps(envelope, default=str))
        except Exception:  # pragma: no cover - defensive
            logger.exception("events_bus.publish failed for %s", event_type)

    def subscribe(
        self, channel: str = CHANNEL
    ) -> "AsyncIterator[dict[str, Any]]":
        return _redis_subscribe(self._client, channel)


async def _redis_subscribe(
    client: redis.Redis, channel: str
) -> "AsyncIterator[dict[str, Any]]":
    """Wrap the blocking ``pubsub.listen()`` in an async generator."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancel = asyncio.Event()

    def _pump() -> None:
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            pubsub.subscribe(channel)
            while not cancel.is_set():
                try:
                    message = pubsub.get_message(
                        timeout=0.2, ignore_subscribe_messages=True
                    )
                except Exception:
                    message = None
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    decoded = json.loads(data)
                except (TypeError, json.JSONDecodeError):
                    logger.warning(
                        "events_bus: dropping malformed message: %r", data
                    )
                    continue
                loop.call_soon_threadsafe(queue.put_nowait, decoded)
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:  # pragma: no cover
                pass
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _pump)
    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item
    finally:
        cancel.set()


# Module-level singleton — overridable by tests.
_default_bus: Bus = RedisBus()


async def publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish ``payload`` on the OCR flow channel as JSON.

    Best-effort: any bus error is logged and swallowed. We never want
    a publish to fail a Celery task or an API call.
    """
    try:
        await _default_bus.publish(event_type, payload)
    except Exception:  # pragma: no cover - defensive
        logger.exception("events_bus.publish_event failed for %s", event_type)


def subscribe_events(
    channel: str = CHANNEL,
) -> "AsyncIterator[dict[str, Any]]":
    """Yield decoded events from ``channel``.

    Uses the module's default bus. Production gets the Redis-backed
    bus; tests inject ``InMemoryBus`` via ``_default_bus``.
    """
    return _default_bus.subscribe(channel)


__all__ = [
    "CHANNEL",
    "Bus",
    "InMemoryBus",
    "RedisBus",
    "publish_event",
    "subscribe_events",
]
