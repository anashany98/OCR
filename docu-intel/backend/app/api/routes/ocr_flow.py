"""OCR flow live + historical endpoints.

Three endpoints live here:

* ``GET /admin/ocr-flow/live`` — REST snapshot of active
  ``ExtractionJob`` rows (status ``pending`` or ``started``). The
  frontend polls this on mount and as a fallback when the SSE
  connection drops.
* ``GET /admin/ocr-flow/stream`` — Server-Sent Events stream of
  lifecycle events (job.queued, job.started, job.finished,
  job.failed) sourced from the Redis pub/sub bus in
  :mod:`app.services.events_bus`.
* ``GET /documents/{id}/flow`` — Per-document historical timeline
  assembled from ``IngestionEvent`` + ``ExtractionJob`` +
  ``DocumentPage`` + ``OcrCascadeAttempt`` by
  :func:`app.services.ocr_flow_timeline.build_document_flow`.

SSE auth: the admin auth dependency validates the bearer token
**from the query string** (the ``EventSource`` browser API cannot
send custom ``Authorization`` headers). The dependency itself is
``require_roles("admin", "gestor", "auditor")`` from
:mod:`app.api.deps`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_roles
from app.models.document import Document, ExtractionJob
from app.models.user import User
from app.services.events_bus import subscribe_events
from app.services.ocr_flow_timeline import build_document_flow


logger = logging.getLogger("app.api.ocr_flow")

router = APIRouter()


@router.get("/admin/ocr-flow/live")
def get_live_jobs(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    """Snapshot of active Celery jobs (pending or started)."""
    rows = db.execute(
        select(ExtractionJob, Document.original_filename)
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(ExtractionJob.status.in_(["pending", "started"]))
        .order_by(ExtractionJob.started_at.desc().nullslast())
        .limit(100)
    ).all()
    return {
        "jobs": [
            {
                "job_id": job.id,
                "document_id": job.document_id,
                "original_filename": filename,
                "job_type": job.job_type,
                "status": job.status,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "retries": job.retries,
                "error": job.error_message,
            }
            for job, filename in rows
        ]
    }


@router.get("/documents/{document_id}/flow")
def get_document_flow(
    document_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    """Per-document historical timeline of OCR flow events."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        "document_id": document_id,
        "original_filename": doc.original_filename,
        "status": doc.status,
        "steps": build_document_flow(db, document_id=document_id),
    }


@router.get("/admin/ocr-flow/stream")
async def stream_events(
    request: Request,
    _user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> StreamingResponse:
    """Server-Sent Events stream of OCR flow lifecycle events.

    The admin auth dependency accepts the bearer token from either
    the standard ``Authorization`` header or a ``?token=…`` query
    parameter (the ``EventSource`` browser API cannot send custom
    headers). See :mod:`app.api.routes.admin_ocr_stats` for the
    dependency itself.
    """

    async def event_source() -> AsyncIterator[bytes]:
        try:
            async for envelope in subscribe_events("ocr_flow"):
                if await request.is_disconnected():
                    return
                # SSE wire format: ``event: <type>\\ndata: <json>\\n\\n``
                event = envelope.get("type", "message")
                data = json.dumps(envelope, default=str)
                yield f"event: {event}\ndata: {data}\n\n".encode("utf-8")
        except asyncio.CancelledError:
            # Client disconnected — clean shutdown of the underlying
            # pubsub subscription is handled by the bus itself.
            return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable buffering on nginx
        },
    )


__all__ = ["router"]
