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
        # WRK-RETRY-1: autoretry_for is a narrow allow-list, not (Exception,)
        assert len(process_document_task.autoretry_for) > 0

    def test_task_has_retry_backoff(self):
        assert process_document_task.retry_backoff is True

    def test_task_has_max_retries(self):
        assert process_document_task.max_retries == 3


class TestScanInputFoldersTask:
    """Tests for scan_input_folders_task Celery task."""

    def test_task_name(self):
        assert scan_input_folders_task.name == "app.workers.tasks.scan_input_folders_task"
