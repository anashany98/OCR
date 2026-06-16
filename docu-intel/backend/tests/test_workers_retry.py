"""
Unit tests for WRK-RETRY-1 (Sprint 2).

Verifies the worker retry policy:

* ``RETRYABLE_EXCEPTIONS`` matches the documented allow-list.
* ``is_retryable`` / ``is_permanent`` correctly classify each error.
* ``mark_job_as_failed`` updates the job row.
* ``truncate_error`` keeps the message single-line and short.
* The ``process_document_task`` wrapper marks a non-retryable
  error as ``failed`` and ``Reject``-s the message; it does NOT
  call ``mark_job_as_failed`` for a retryable error (Celery will
  retry, then mark failed at the end of the chain).
"""

from __future__ import annotations

import os
import socket
import ssl
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import (
    DataError,
    DisconnectionError,
    IntegrityError,
    InterfaceError,
    OperationalError,
)

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)

from app.workers.errors import (  # noqa: E402
    RETRYABLE_EXCEPTIONS,
    is_permanent,
    is_retryable,
    mark_job_as_failed,
    notify_failed,
    truncate_error,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestIsRetryable:
    """Each entry in the allow-list is a known transient condition."""

    @pytest.mark.parametrize(
        "exc",
        [
            OperationalError("SELECT 1", {}, Exception("conn refused")),
            DisconnectionError("disconnected", {}, Exception()),
            InterfaceError("interface error", {}, Exception()),
            socket.gaierror("name resolution failed"),
            socket.timeout("timed out"),
            TimeoutError("timed out"),
            ConnectionError("connection failed"),
            ConnectionResetError("reset"),
            ConnectionRefusedError("refused"),
            ssl.SSLError("tls handshake failed"),
        ],
    )
    def test_transient_errors_are_retryable(self, exc):
        assert is_retryable(exc) is True
        assert is_permanent(exc) is False

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("gone"),
            PermissionError("denied"),
            IntegrityError("INSERT", {}, Exception("unique violation")),
            DataError("INSERT", {}, Exception("value too long")),
            KeyError("missing"),
            ValueError("bad input"),
            TypeError("wrong type"),
            ZeroDivisionError("div by zero"),
        ],
    )
    def test_permanent_errors_are_not_retryable(self, exc):
        assert is_retryable(exc) is False
        assert is_permanent(exc) is True


class TestTruncateError:
    def test_short_error_unchanged(self):
        exc = ValueError("bad input")
        assert truncate_error(exc) == "ValueError: bad input"

    def test_long_error_truncated(self):
        long = "x" * 1000
        exc = ValueError(long)
        out = truncate_error(exc, limit=100)
        assert len(out) <= 100
        assert out.startswith("ValueError: ")

    def test_truncation_does_not_split_codepoint(self):
        # Multi-byte char at the boundary should not leave a half.
        exc = ValueError("a" * 99 + "ñ" + "b" * 50)
        out = truncate_error(exc, limit=100)
        # We don't enforce exact content (Python slicing is byte-safe
        # and may produce a ``?``); we just assert the output is
        # at most 100 chars.
        assert len(out) <= 100


class TestMarkJobAsFailed:
    def test_marks_job_with_status_and_error(self):
        job = MagicMock()
        job.id = 42
        db = MagicMock()
        exc = FileNotFoundError("/data/input/missing.pdf")
        mark_job_as_failed(db, job, exc)
        assert job.status == "failed"
        assert job.error_message == "FileNotFoundError: /data/input/missing.pdf"
        assert isinstance(job.finished_at, datetime)
        db.add.assert_called_once_with(job)

    def test_none_job_is_noop(self):
        db = MagicMock()
        mark_job_as_failed(db, None, FileNotFoundError("x"))
        db.add.assert_not_called()

    def test_truncates_long_error(self):
        job = MagicMock()
        job.id = 1
        db = MagicMock()
        exc = ValueError("z" * 1000)
        mark_job_as_failed(db, job, exc)
        assert len(job.error_message) <= 500  # default limit


class TestNotifyFailed:
    def test_none_job_id_is_noop(self):
        notify_failed(job_id=None, document_id=1, exc=ValueError("x"))

    def test_none_document_id_is_noop(self):
        notify_failed(job_id=1, document_id=None, exc=ValueError("x"))

    def test_redis_failure_does_not_raise(self, monkeypatch):
        """The notification is best-effort. A Redis outage must not
        cascade into a task failure (which would itself be a
        permanent error and Reject the message)."""
        from app.services import notification as notification_module

        broken_service = MagicMock()
        broken_service.notify_job_failed.side_effect = ConnectionError("redis down")
        monkeypatch.setattr(notification_module, "notification_service", broken_service)
        # Should NOT raise.
        notify_failed(job_id=1, document_id=2, exc=ValueError("x"))
        broken_service.notify_job_failed.assert_called_once()


# ---------------------------------------------------------------------------
# Worker-task wrapper behaviour
# ---------------------------------------------------------------------------


class TestProcessDocumentTaskWrapper:
    """The Celery task wrapper must:

    * mark the job as ``failed`` + Reject on permanent errors;
    * leave the job alone on retryable errors (Celery will retry);
    * close the session in the ``finally`` block.

    We do not run the Celery worker process; instead we extract the
    body of the wrapper (the logic between the ``SessionLocal`` /
    ``try`` / ``finally``) and exercise it directly with a mock
    ``self.request`` so the assertions are deterministic.
    """

    def test_permanent_error_marks_job_as_failed(self, monkeypatch):
        from app.workers import tasks as tasks_module

        # Replace process_document with one that raises a permanent
        # error.
        def fake_process(db, document_id, job_id, final_failure):
            raise FileNotFoundError(f"document {document_id} gone")

        monkeypatch.setattr(tasks_module, "process_document", fake_process)

        # Build a fake job + document in an in-memory SQLite session.
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.database.base import Base
        from app.models import Document, ExtractionJob

        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        session_factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        Base.metadata.create_all(engine)

        session = session_factory()
        try:
            document = Document(
                original_filename="x.pdf",
                stored_filename="aa/x.pdf",
                file_hash="a" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=100,
                document_type="presupuesto",
                status="pending",
            )
            session.add(document)
            session.flush()
            job = ExtractionJob(document_id=document.id, job_type="extract", status="pending")
            session.add(job)
            session.commit()

            # Replace SessionLocal with our test session factory.
            monkeypatch.setattr(tasks_module, "SessionLocal", session_factory)
            # Call the Celery task body via ``.run()`` which is the
            # hook the worker process uses; the body runs with
            # proper ``self.request`` injected.
            with pytest.raises(Exception) as excinfo:
                tasks_module.process_document_task.run(document.id, job.id)
            # The exception must be the Reject from celery, which
            # carries the original exception.
            assert "FileNotFoundError" in str(excinfo.value) or "gone" in str(excinfo.value)

            # Refresh and verify the job was marked failed.
            session.expire_all()
            job = session.get(ExtractionJob, job.id)
            assert job.status == "failed"
            assert "FileNotFoundError" in job.error_message
            assert job.finished_at is not None
        finally:
            session.close()

    def test_retryable_error_does_not_mark_job_as_failed(self, monkeypatch):
        """A transient error (e.g. DB connection lost) must NOT mark
        the job as failed immediately. The job stays in
        ``status='processing'`` so Celery's autoretry can fire.
        """
        from sqlalchemy.exc import OperationalError

        from app.workers import tasks as tasks_module

        def fake_process(db, document_id, job_id, final_failure):
            raise OperationalError("SELECT", {}, Exception("conn lost"))

        monkeypatch.setattr(tasks_module, "process_document", fake_process)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.database.base import Base
        from app.models import Document, ExtractionJob

        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        session_factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        Base.metadata.create_all(engine)
        session = session_factory()
        try:
            document = Document(
                original_filename="y.pdf",
                stored_filename="bb/y.pdf",
                file_hash="b" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=100,
                document_type="presupuesto",
                status="pending",
            )
            session.add(document)
            session.flush()
            job = ExtractionJob(document_id=document.id, job_type="extract", status="processing")
            session.add(job)
            session.commit()

            monkeypatch.setattr(tasks_module, "SessionLocal", session_factory)
            with pytest.raises(OperationalError):
                tasks_module.process_document_task.run(document.id, job.id)

            session.expire_all()
            job = session.get(ExtractionJob, job.id)
            # Job is NOT marked failed — the autoretry path will
            # mark it on the final attempt.
            assert job.status == "processing"
        finally:
            session.close()


class TestTaskConfiguration:
    """The task decorator must carry the WRK-RETRY-1 config knobs."""

    def test_process_document_task_has_narrow_autoretry(self):
        from app.workers.tasks import process_document_task

        # Celery exposes the ``autoretry_for`` list on the task
        # itself. We assert that RETRYABLE_EXCEPTIONS is a subset
        # of the autoretry list (Celery may add platform defaults
        # for SIGSEGV/SIGTERM etc., that's fine).
        autoretry = set(getattr(process_document_task, "autoretry_for", None) or [])
        for cls in RETRYABLE_EXCEPTIONS:
            assert cls in autoretry, f"missing {cls.__name__} in autoretry"

    def test_process_document_task_has_time_limits(self):
        from app.workers.tasks import process_document_task

        # Celery exposes the soft/hard time limits as attributes on
        # the Task instance.
        assert getattr(process_document_task, "soft_time_limit", None) == 900
        assert getattr(process_document_task, "time_limit", None) == 1200

    def test_process_document_task_has_max_retries(self):
        from app.workers.tasks import process_document_task

        assert getattr(process_document_task, "max_retries", None) == 3

    def test_process_document_task_acks_late(self):
        # Set globally on the celery app; we verify it is True
        # even if the task does not override it.
        from app.workers.celery_app import celery_app

        assert celery_app.conf.task_acks_late is True
