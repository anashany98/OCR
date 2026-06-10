"""Pipeline metrics: documents, watcher errors, queue status, DB snapshot.

``document_status_counts`` is the only function in the metrics
package that touches the database: it groups documents by
status and feeds the ``docuintel_documents_by_status`` gauge. The
rest of the file is pure in-memory state.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document

from ._registry import (
    DOCUMENTS_BY_STATUS,
    DOCUMENTS_FAILED,
    DOCUMENTS_PROCESSED,
    JOBS_PENDING_BY_QUEUE,
    WATCHER_ERRORS,
)


def track_document_processed(count: int = 1) -> None:
    """Record that ``count`` documents finished processing successfully."""
    if count <= 0:
        return
    DOCUMENTS_PROCESSED.inc(count)


def track_document_failed(count: int = 1) -> None:
    """Record that ``count`` documents failed processing."""
    if count <= 0:
        return
    DOCUMENTS_FAILED.inc(count)


def track_watcher_error(count: int = 1) -> None:
    """Record that the file watcher hit ``count`` ingestion errors."""
    if count <= 0:
        return
    WATCHER_ERRORS.inc(count)


def update_queue_status_snapshot(snapshot) -> None:
    """Refresh the per-queue pending gauge from a Celery
    ``inspect().stats()`` snapshot.

    The snapshot is a dict-like of ``{queue_name: {"pending": N,
    ...}}``. We accept the loose shape and look only at the
    ``pending`` key per queue.
    """
    queues = getattr(snapshot, "queues", snapshot) or {}
    JOBS_PENDING_BY_QUEUE.clear()
    for queue_name, values in queues.items():
        if isinstance(values, dict):
            pending = int(values.get("pending", 0) or 0)
            JOBS_PENDING_BY_QUEUE.labels(queue=str(queue_name)).set(pending)


def document_status_counts(db: Session) -> dict[str, int]:
    """Group non-deleted documents by their ``status`` field.

    Returns a plain dict so the caller (and tests) can compare
    it without going through Prometheus' internals. The
    renderer (``endpoint.py``) consumes both this dict and the
    metrics module's per-status gauge; the gauge is refreshed
    in :func:`refresh_documents_by_status_gauge`.
    """
    rows = db.execute(
        select(Document.status, func.count())
        .where(Document.deleted_at.is_(None))
        .group_by(Document.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def refresh_documents_by_status_gauge(db: Session) -> dict[str, int]:
    """Read the per-status counts from the DB and feed the gauge.

    Returns the same dict so the endpoint renderer can both
    surface it to the legacy ``get_metrics()`` flat output and
    to the Prometheus exposition.
    """
    counts = document_status_counts(db)
    DOCUMENTS_BY_STATUS.clear()
    for status, count in counts.items():
        DOCUMENTS_BY_STATUS.labels(status=status).set(count)
    return counts
