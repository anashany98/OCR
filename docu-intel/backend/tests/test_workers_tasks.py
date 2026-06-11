"""
Unit tests for app.workers.tasks
Tests Celery task definitions and behavior.
"""
from __future__ import annotations

import os

import pytest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

# Import after env is set
from app.workers.tasks import process_document_task, scan_input_folders_task


class TestProcessDocumentTask:
    """Tests for process_document_task Celery task."""

    def test_task_name(self):
        assert process_document_task.name == "app.workers.tasks.process_document_task"

    def test_task_has_autoretry(self):
        # Verify autoretry is configured - exception tuple should include Exception
        assert process_document_task.autoretry_for == (Exception,)

    def test_task_has_retry_backoff(self):
        assert process_document_task.retry_backoff is True

    def test_task_has_max_retries(self):
        assert process_document_task.max_retries == 2

    def test_task_is_bound(self):
        # bind=True means first argument is self (the task itself)
        assert process_document_task.bind is True


class TestScanInputFoldersTask:
    """Tests for scan_input_folders_task Celery task."""

    def test_task_name(self):
        assert scan_input_folders_task.name == "app.workers.tasks.scan_input_folders_task"

    def test_task_is_not_bound(self):
        # scan_input_folders_task should not be bound (no bind=True)
        assert scan_input_folders_task.bind is None or scan_input_folders_task.bind is False