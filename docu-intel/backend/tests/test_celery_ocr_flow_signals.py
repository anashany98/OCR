"""Tests for the Celery signal hooks that publish OCR flow events.

We invoke the signal handlers directly (Celery's signal API is
synchronous) and assert that the in-memory bus receives the
expected events.
"""
from __future__ import annotations

import pytest
from celery.signals import (
    before_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
)

from app.services import events_bus
from app.services.events_bus import InMemoryBus
from app.workers import celery_app


@pytest.fixture
def bus(monkeypatch) -> InMemoryBus:
    fake = InMemoryBus()
    monkeypatch.setattr(events_bus, "_default_bus", fake)
    return fake


def _tracked_task() -> str:
    return "app.workers.tasks.process_document_task"


def _make_pretend_task(name: str):
    """Build a minimal object with ``.name`` so the signal handlers accept it."""

    class _Task:
        pass

    t = _Task()
    t.name = name
    return t


def test_publish_signal_emits_job_queued(bus: InMemoryBus):
    before_task_publish.send(
        sender=_tracked_task(),
        headers={"task": _tracked_task()},
        body=((42, 1),),  # positional args tuple
    )
    assert bus.published == [
        {
            "type": "job.queued",
            "task": _tracked_task(),
            "document_id": 42,
        }
    ]


def test_publish_signal_ignores_unknown_tasks(bus: InMemoryBus):
    before_task_publish.send(
        sender="app.workers.webhooks_tasks.deliver_pending_webhooks_task",
        headers={"task": "app.workers.webhooks_tasks.deliver_pending_webhooks_task"},
        body=((),),
    )
    assert bus.published == []


def test_prerun_emits_job_started(bus: InMemoryBus):
    task = _make_pretend_task(_tracked_task())
    task_prerun.send(sender=task, task=task, task_id="t-1", args=(7, 99), kwargs=None)
    assert bus.published == [
        {
            "type": "job.started",
            "task": _tracked_task(),
            "task_id": "t-1",
            "document_id": 7,
        }
    ]


def test_postrun_emits_job_finished(bus: InMemoryBus):
    task = _make_pretend_task(_tracked_task())
    task_postrun.send(
        sender=task,
        task=task,
        task_id="t-1",
        args=(7, 99),
        kwargs=None,
        state="SUCCESS",
        runtime=1.234,
    )
    assert len(bus.published) == 1
    evt = bus.published[0]
    assert evt["type"] == "job.finished"
    assert evt["task_id"] == "t-1"
    assert evt["document_id"] == 7
    assert evt["state"] == "SUCCESS"
    assert evt["runtime_s"] == 1.234


def test_failure_emits_job_failed(bus: InMemoryBus):
    task = _make_pretend_task(_tracked_task())
    task_failure.send(
        sender=task,
        task=task,
        task_id="t-1",
        args=(7, 99),
        kwargs=None,
        exception=RuntimeError("boom"),
    )
    assert bus.published == [
        {
            "type": "job.failed",
            "task": _tracked_task(),
            "task_id": "t-1",
            "document_id": 7,
            "error": "boom",
        }
    ]


def test_extract_document_id_handles_dict_args():
    """Batch tasks pass ``{'document_ids': [...]}`` — we accept that gracefully."""
    assert celery_app._extract_document_id(({"document_id": 12},), None) == 12
    assert celery_app._extract_document_id((11,), None) == 11
    assert celery_app._extract_document_id((), None) is None
    assert celery_app._extract_document_id(("string",), None) is None
    assert celery_app._extract_document_id(None, None) is None
