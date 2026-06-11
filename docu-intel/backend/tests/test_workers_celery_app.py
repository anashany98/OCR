"""
Unit tests for app.workers.celery_app
Tests Celery app configuration and task routing.
"""
from __future__ import annotations

import os

import pytest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from app.workers.celery_app import celery_app


class TestCeleryAppConfig:
    """Tests for celery_app configuration."""

    def test_broker_is_redis(self):
        assert "redis" in celery_app.broker_url

    def test_result_backend_is_redis(self):
        assert "redis" in celery_app.result_backend

    def test_task_serializer_is_json(self):
        assert celery_app.conf.task_serializer == "json"

    def test_accept_content_is_json(self):
        assert celery_app.conf.accept_content == ["json"]

    def test_timezone_is_madrid(self):
        assert celery_app.conf.timezone == "Europe/Madrid"

    def test_worker_prefetch_multiplier_is_1(self):
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_task_acks_late_is_true(self):
        assert celery_app.conf.task_acks_late is True

    def test_broker_connection_retry_on_startup(self):
        assert celery_app.conf.broker_connection_retry_on_startup is True

    def test_task_routes_defined(self):
        routes = celery_app.conf.task_routes
        assert "app.workers.tasks.process_document_task" in routes
        assert "app.workers.tasks.scan_input_folders_task" in routes

    def test_process_document_uses_ocr_heavy_queue(self):
        routes = celery_app.conf.task_routes
        task_route = routes["app.workers.tasks.process_document_task"]
        assert task_route["queue"] == "ocr_heavy"
        assert task_route["routing_key"] == "ocr.heavy"

    def test_scan_folders_uses_maintenance_queue(self):
        routes = celery_app.conf.task_routes
        task_route = routes["app.workers.tasks.scan_input_folders_task"]
        assert task_route["queue"] == "maintenance"

    def test_worker_pool_is_prefork(self):
        assert celery_app.conf.worker_pool == "prefork"

    def test_worker_max_tasks_per_child_is_50(self):
        assert celery_app.conf.worker_max_tasks_per_child == 50

    def test_task_default_queue_is_text_fast(self):
        assert celery_app.conf.task_default_queue == "text_fast"

    def test_beat_schedule_has_scan_task(self):
        beat = celery_app.conf.beat_schedule
        assert "scan-input-folders" in beat
        assert beat["scan-input-folders"]["task"] == "app.workers.tasks.scan_input_folders_task"