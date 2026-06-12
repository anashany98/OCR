"""Tests for the OCR flow events bus.

The bus is a thin wrapper around a pub/sub transport. Production
goes through Redis; tests inject ``InMemoryBus`` so the round-trip
is deterministic and does not depend on fakeredis (which has known
limitations delivering pub/sub messages within a single process).
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import events_bus
from app.services.events_bus import InMemoryBus


@pytest.fixture
def bus(monkeypatch) -> InMemoryBus:
    """Replace the default bus with an in-memory one for this test."""
    fake = InMemoryBus()
    monkeypatch.setattr(events_bus, "_default_bus", fake)
    return fake


def test_publish_then_subscribe_receives_event(bus: InMemoryBus):
    async def _go() -> dict:
        # Subscribe first, then publish.
        iterator = events_bus.subscribe_events()
        received: asyncio.Task = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)  # let the subscriber register its queue
        await events_bus.publish_event(
            "job.started", {"document_id": 1, "task": "tesseract"}
        )
        return await asyncio.wait_for(received, timeout=1.0)

    received = asyncio.run(_go())
    assert received == {
        "type": "job.started",
        "document_id": 1,
        "task": "tesseract",
    }


def test_publish_swallows_bus_errors(monkeypatch):
    """A publish that fails must never raise — events are best-effort."""

    class _Boom:
        async def publish(self, *args, **kwargs):
            raise RuntimeError("bus down")

    monkeypatch.setattr(events_bus, "_default_bus", _Boom())

    async def _go() -> None:
        await events_bus.publish_event("job.failed", {"document_id": 1})

    # Should not raise.
    asyncio.run(_go())


def test_multiple_subscribers_each_get_the_event(bus: InMemoryBus):
    async def _go() -> list[dict]:
        a = events_bus.subscribe_events()
        b = events_bus.subscribe_events()
        ta = asyncio.create_task(a.__anext__())
        tb = asyncio.create_task(b.__anext__())
        await asyncio.sleep(0)
        await events_bus.publish_event("job.finished", {"document_id": 7})
        return await asyncio.gather(
            asyncio.wait_for(ta, timeout=1.0),
            asyncio.wait_for(tb, timeout=1.0),
        )

    a, b = asyncio.run(_go())
    assert a == {"type": "job.finished", "document_id": 7}
    assert b == {"type": "job.finished", "document_id": 7}
