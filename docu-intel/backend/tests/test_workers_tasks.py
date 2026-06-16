"""
Unit tests for app.workers.tasks
Tests Celery task definitions and behavior.
"""
from __future__ import annotations

import os
import inspect

import pytest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

# Import after env is set
from app.workers.tasks import process_document_task, scan_input_folders_task


def _is_bound(task) -> bool:
    """Reliable Celery 5 introspection: a task is bound when its
    ``__wrapped__`` attribute is a bound method (i.e. ``self`` is in
    the wrapped callable's argument list).

    Celery 5 no longer exposes ``bind`` as a plain bool; ``task.bind``
    is now always a bound method ``Task.bind`` regardless of the
    underlying task's binding state. ``task.typing`` is also always
    ``True`` in Celery 5, so neither attribute discriminates.
    """
    wrapped = getattr(task, "__wrapped__", None)
    if wrapped is None:
        return False
    try:
        first_arg = wrapped.__func__.__code__.co_varnames[0]
    except AttributeError:
        # ``__wrapped__`` is already a plain function (unbound task).
        return False
    return first_arg == "self"


class TestProcessDocumentTask:
    """Tests for process_document_task Celery task."""

    def test_task_name(self):
        assert process_document_task.name == "app.workers.tasks.process_document_task"

    def test_task_has_autoretry(self):
        # WRK-RETRY-1 (Sprint 1): the autoretry allow-list is a narrow
        # tuple of transient errors (network/DB), NOT ``(Exception,)``.
        # ``OperationalError`` is the first entry; verifying the
        # allow-list is *narrower* than ``Exception`` is the contract.
        assert process_document_task.autoretry_for is not None
        assert process_document_task.autoretry_for != (Exception,)
        assert Exception not in process_document_task.autoretry_for
        # The retryable set must include the canonical transient DB error.
        from sqlalchemy.exc import OperationalError
        assert OperationalError in process_document_task.autoretry_for

    def test_task_has_retry_backoff(self):
        assert process_document_task.retry_backoff is True

    def test_task_has_max_retries(self):
        # The current production value is 3 (see app/workers/tasks.py).
        assert process_document_task.max_retries == 3

    def test_task_is_bound(self):
        # bind=True: the original function's first parameter is ``self``.
        assert _is_bound(process_document_task) is True


class TestScanInputFoldersTask:
    """Tests for scan_input_folders_task Celery task."""

    def test_task_name(self):
        assert scan_input_folders_task.name == "app.workers.tasks.scan_input_folders_task"

    def test_task_is_not_bound(self):
        # No ``bind=True`` on the decorator: the original function takes
        # no ``self``. The previous assertion
        # ``task.bind is None or task.bind is False`` was specific to
        # Celery 4; in Celery 5 ``task.bind`` is a bound method regardless.
        assert _is_bound(scan_input_folders_task) is False