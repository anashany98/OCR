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
    PARSER_FALLBACK_FAILURES,
    WATCHER_ERRORS,
    WORKER_INIT_FAILURES,
)

# Allow-list of ``stage`` values for ``track_worker_init_failure``.
# Anything outside the list is bucketed to ``"other"`` so a
# buggy caller cannot blow up the Prometheus label cardinality.
_ALLOWED_INIT_STAGES = frozenset(
    {
        "ocr_preload",
        "yolo_preload",
        "reranker_preload",
        "embedding_preload",
        "other",
    }
)

# OPS-2: bounded label sets for parser-fallback failure counters.
# Each (stage, kind) combination is a different fallback path;
# the parser logs a warning and increments the counter so
# operators can see WHICH fallback degraded and how often,
# instead of "some doc came out without entities" being the
# only signal.
_ALLOWED_PARSER_STAGES = frozenset(
    {
        # Standalone image parser, vision transcription path.
        "image_vision_transcribe",
        # PDF page parser, vision transcription path.
        "pdf_vision_table",
        # PDF page parser, pdfplumber table extraction path.
        "pdfplumber_table",
        # PDF page renderer: JPEG and PNG fallbacks inside
        # ``_render_page_to_image``.
        "pdf_render_jpeg",
        "pdf_render_png",
        # PDF page renderer: the final stage that moves the
        # encoded bytes to the canonical on-disk path.
        # OPS-1 added this so a write/rename failure on the
        # final path is observable in /metrics rather than
        # crashing the DPI ladder silently.
        "pdf_render_finalise",
        # PDF page parser, OCR engine crash on a rendered
        # image (DPI ladder moves on, but the page ends up
        # blank if every step fails).
        "pdf_ocr_extract",
        # PDF page parser, rename to canonical filename for
        # the viewer.
        "pdf_rename_canonical",
        # Anything new will land here; bounded so we don't blow up
        # cardinality if a caller passes a typo.
        "other",
    }
)
_ALLOWED_PARSER_KINDS = frozenset(
    {
        "exception",
        "import_error",
        "other",
    }
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


def track_worker_init_failure(stage: str, count: int = 1) -> None:
    """Record a failure in the Celery ``worker_process_init`` hook.

    The ``stage`` label is bucketed: any value outside
    :data:`_ALLOWED_INIT_STAGES` is mapped to ``"other"`` so the
    Prometheus series count stays bounded.

    OCR-INIT-1 (Sprint 2): used by the OCR preload hook in
    ``app.workers.celery_app`` so that a missing Paddle
    install or a broken model download is visible in the
    metrics endpoint, not just a log line that the operator
    might miss.
    """
    if count <= 0:
        return
    safe_stage = stage if stage in _ALLOWED_INIT_STAGES else "other"
    WORKER_INIT_FAILURES.labels(stage=safe_stage).inc(count)


def track_parser_fallback_failure(stage: str, kind: str = "exception", count: int = 1) -> None:
    """Record a swallowed exception in a parser fallback path.

    OPS-2: the standalone image parser, the PDF parser and the
    pdfplumber table extractor used to ``except Exception: pass``
    on their fallback paths, which made degradation invisible —
    the only signal that the vision model was failing was "the
    document came out without entities". This counter gives the
    operator per-(stage, kind) visibility so the on-call can
    distinguish "vision model OOM" from "pdfplumber strategy
    rejected the layout".

    Both labels are bucketed against an allow-list; anything
    outside is mapped to ``"other"`` so a caller passing a
    typo or a new value can never blow up Prometheus
    cardinality.
    """
    if count <= 0:
        return
    safe_stage = stage if stage in _ALLOWED_PARSER_STAGES else "other"
    safe_kind = kind if kind in _ALLOWED_PARSER_KINDS else "other"
    PARSER_FALLBACK_FAILURES.labels(stage=safe_stage, kind=safe_kind).inc(count)


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


def track_stale_jobs_reset(count: int = 1) -> None:
    from . import _registry

    _registry.STALE_JOBS_RESET.inc(count)


def track_notification_failure(channel: str = "unknown") -> None:
    from . import _registry

    _registry.NOTIFICATION_FAILURES.labels(channel=channel).inc()


# ---------------------------------------------------------------------------
# P0.1 — Per-stage pipeline timing
# ---------------------------------------------------------------------------

_ALLOWED_STAGES = frozenset(
    {
        "probe",
        "render",
        "ocr",
        "persist",
        "classification",
        "extraction",
        "chunking",
        "embedding",
        "hyperextract",
        "total",
    }
)


def track_stage_duration(stage: str, duration: float) -> None:
    """Record the wall-clock duration of a processing stage.

    ``stage`` is bucketed: values outside :data:`_ALLOWED_STAGES` are
    mapped to ``"total"`` so caller typos never explode cardinality.
    """
    if duration < 0:
        return
    from . import _registry

    safe = stage if stage in _ALLOWED_STAGES else "total"
    _registry.STAGE_DURATION.labels(stage=safe).observe(duration)


def track_stage_failure(stage: str, reason: str = "exception") -> None:
    """Record a failure at a specific processing stage."""
    from . import _registry

    safe = stage if stage in _ALLOWED_STAGES else "total"
    _registry.STAGE_FAILURES.labels(
        stage=safe,
        reason=(reason or "unknown").strip()[:40] or "unknown",
    ).inc()


def track_page_processed(route: str = "unknown", engine: str = "unknown") -> None:
    """Record that one page was processed, with routing and engine labels."""
    from . import _registry

    _registry.PAGES_PROCESSED.labels(
        route=(route or "unknown").strip()[:30] or "unknown",
        engine=(engine or "unknown").strip()[:30] or "unknown",
    ).inc()
