"""Build the per-document historical timeline shown in the OCR flow UI.

The timeline is assembled by reading four existing sources and
merging them by timestamp. We do **not** introduce a new table for
this view — the cascade is represented at 'every tier tried per
page' granularity via the ``OcrCascadeAttempt`` table.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import DocumentPage, ExtractionJob
from app.models.ocr_cascade import OcrCascadeAttempt
from app.models.operations import IngestionEvent


def build_document_flow(session: Session, *, document_id: int) -> list[dict[str, Any]]:
    """Return a chronologically ordered list of timeline steps for a document.

    Reads four existing sources plus the per-tier cascade log:

    * ``IngestionEvent`` — any event the watcher/parser emitted.
    * ``ExtractionJob`` — Celery job lifecycle.
    * ``DocumentPage`` — one row per page with the winning engine.
    * ``OcrCascadeAttempt`` — every tier tried per page. Attached
      to the matching ``page.processed`` step under
      ``details.cascade_attempts`` so the UI can render the full
      trace.
    """
    steps: list[dict[str, Any]] = []

    for ev in session.scalars(
        select(IngestionEvent).where(IngestionEvent.document_id == document_id)
    ).all():
        steps.append(
            {
                "kind": ev.event_type,
                "at": ev.created_at.isoformat() if ev.created_at else None,
                "details": ev.details_json or {},
                "error": ev.error_message,
            }
        )

    for job in session.scalars(
        select(ExtractionJob).where(ExtractionJob.document_id == document_id)
    ).all():
        at = job.started_at or job.finished_at
        steps.append(
            {
                "kind": "extraction_job",
                "at": at.isoformat() if at else None,
                "details": {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "retries": job.retries,
                },
                "error": job.error_message,
            }
        )

    # One query for every page, then a single follow-up query for all
    # cascade attempts. Keeps the assembler O(1) round-trips regardless
    # of document size.
    pages = session.scalars(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
    ).all()
    attempts_by_page: dict[int, list[OcrCascadeAttempt]] = {p.id: [] for p in pages}
    if pages:
        rows = session.scalars(
            select(OcrCascadeAttempt)
            .where(OcrCascadeAttempt.document_id == document_id)
            .order_by(
                OcrCascadeAttempt.page_id.asc(),
                OcrCascadeAttempt.tier_index.asc(),
            )
        ).all()
        for row in rows:
            attempts_by_page.setdefault(row.page_id, []).append(row)

    for page in pages:
        cascade_attempts = [
            {
                "id": a.id,
                "tier": a.tier,
                "tier_index": a.tier_index,
                "success": a.success,
                "duration_ms": a.duration_ms,
                "confidence": a.confidence,
                "chars": a.chars,
                "reason": a.reason,
                "error_message": a.error_message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in attempts_by_page.get(page.id, [])
        ]
        steps.append(
            {
                "kind": "page.processed",
                "at": page.created_at.isoformat() if page.created_at else None,
                "details": {
                    "page_id": page.id,
                    "page_number": page.page_number,
                    "ocr_engine": page.ocr_engine,
                    "ocr_engine_version": page.ocr_engine_version,
                    "ocr_confidence": page.ocr_confidence,
                    "processing_time_ms": page.processing_time_ms,
                    "attempts": page.attempts,
                    "page_status": page.page_status,
                    "cascade_attempts": cascade_attempts,
                },
                "error": page.error_message,
            }
        )

    steps.sort(key=lambda s: s.get("at") or "")
    return steps


__all__ = ["build_document_flow"]
