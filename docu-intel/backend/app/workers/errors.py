"""Shared worker-task infrastructure (WRK-RETRY-1 / Sprint 2).

The pre-Sprint-2 code used ``autoretry_for=(Exception,)`` on every
worker task, which means a permanent error (``FileNotFoundError``,
``IntegrityError`` on a duplicate, a malformed PDF that raises
``ValueError`` after 30 seconds of PaddleOCR work) was retried up
to ``max_retries`` times before being marked as failed. The retry
added nothing: the file is still missing, the PDF is still
malformed. Meanwhile a transient error (``OperationalError`` on a
disconnected DB, a 503 from the LLM provider) WAS worth retrying
but the blanket catch was so noisy that the real failures were
hard to spot in the dashboard.

The fix in this module:

* :data:`RETRYABLE_EXCEPTIONS` is the **allow-list** of exception
  types that are worth retrying. Anything not in this tuple is
  permanent and must be marked ``failed`` immediately.
* :func:`mark_job_as_failed` updates an ``ExtractionJob`` to
  ``status='failed'`` with a truncated error message and
  ``finished_at=now``. Called from the task wrapper on
  non-retryable errors.
* :func:`notify_failed` publishes a Redis pub/sub event so the
  admin UI / on-call can react. The notification is best-effort;
  a Redis outage does NOT itself cause a task to fail.

The task wrappers (``process_document_task``, etc.) catch
:data:`RETRYABLE_EXCEPTIONS` and re-raise so Celery's
``autoretry_for`` triggers; they catch everything else, call
:func:`mark_job_as_failed` + :func:`notify_failed`, and ``Reject``
the message so it is not re-queued.
"""

from __future__ import annotations

import logging
import socket
import ssl
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import ExtractionJob


logger = logging.getLogger("app.workers.errors")


# Tuple of exception types that are *worth* retrying. Anything not
# in this list is treated as permanent: the task is marked
# ``failed`` immediately and the message is ``Reject``-ed so
# the worker does not pick it up again.
#
# Included:
#   * ``OperationalError`` / ``DisconnectionError`` / ``InterfaceError``:
#     transient DB connection issues (Postgres restart, connection
#     pool exhaustion). The DB will be back on the next attempt.
#   * ``socket.gaierror`` / ``socket.timeout`` / ``TimeoutError`` /
#     ``ConnectionError`` / ``ConnectionResetError``:
#     transient network failures (LLM provider down, webhook
#     receiver down, etc.). These almost always self-resolve.
#   * ``ssl.SSLError``: transient TLS handshake failures (clock
#     skew between hosts, intermediate proxy restart).
#
# Excluded (these are permanent and MUST NOT be retried):
#   * ``FileNotFoundError``: the file is gone.
#   * ``PermissionError``: the file is locked / perms changed.
#   * ``IntegrityError``: the row already exists or a FK target
#     vanished. Retrying just spams the log.
#   * ``DataError``: the value violates a column type / check
#     constraint. The input is bad, not the connection.
#   * ``KeyError`` / ``ValueError``: bug in our code, retrying
#     won't help.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OperationalError,
    DisconnectionError,
    InterfaceError,
    socket.gaierror,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    ssl.SSLError,
)


def is_retryable(exc: BaseException) -> bool:
    """Return True if ``exc`` is in the allow-list of retryable types."""
    # Walk the MRO: a ``ConnectionResetError`` is also an
    # ``OSError`` (which is also ``ConnectionError`` in Python 3.3+)
    # so checking via isinstance is enough.
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def is_permanent(exc: BaseException) -> bool:
    """Inverse of :func:`is_retryable`. Permanent = do not retry."""
    return not is_retryable(exc)


def truncate_error(exc: BaseException, *, limit: int = 500) -> str:
    """Return a single-line representation of ``exc`` for log/DB.

    The full stack trace is captured by the logger at the
    call site; we only persist a short, single-line summary so
    the ``extraction_jobs.error_message`` column does not balloon
    on a long traceback.
    """
    return f"{type(exc).__name__}: {exc}"[:limit]


def mark_job_as_failed(
    db: "Session",
    job: "ExtractionJob | None",
    exc: BaseException,
) -> None:
    """Mark ``job`` as ``failed`` with a truncated error message.

    No-op if ``job`` is ``None`` (e.g. the caller couldn't load it
    because the DB connection is down). The caller is responsible
    for committing the session after this function returns.
    """
    if job is None:
        return
    try:
        job.status = "failed"
        job.error_message = truncate_error(exc)
        job.finished_at = datetime.now(timezone.utc)
        db.add(job)
    except Exception:  # pragma: no cover - defensive
        # If the job itself can't be updated (e.g. the session is
        # in a bad state), we don't want to mask the original
        # exception with this one. Log and move on.
        logger.exception("mark_job_as_failed job_id=%s", getattr(job, "id", "?"))


def notify_failed(
    *,
    job_id: int | None,
    document_id: int | None,
    exc: BaseException,
) -> None:
    """Publish a ``job_failed`` notification to Redis pub/sub.

    Best-effort: a Redis outage MUST NOT itself cause the worker
    task to fail (otherwise we cascade the failure). The
    underlying :func:`NotificationService.notify_job_failed` already
    swallows transport errors and returns ``False`` in that case.
    """
    if job_id is None or document_id is None:
        return
    try:
        from app.services.notification import notification_service

        notification_service.notify_job_failed(
            job_id=job_id,
            document_id=document_id,
            error=truncate_error(exc),
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "notify_failed job_id=%s document_id=%s",
            job_id,
            document_id,
        )


__all__ = [
    "RETRYABLE_EXCEPTIONS",
    "is_retryable",
    "is_permanent",
    "truncate_error",
    "mark_job_as_failed",
    "notify_failed",
]
