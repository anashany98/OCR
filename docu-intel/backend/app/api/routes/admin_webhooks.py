"""Admin endpoints for inspecting and managing the webhook outbox.

Mounted by the admin router. Exposes:

* ``GET /admin/webhooks/outbox``            - list pending / sending / delivered
* ``GET /admin/webhooks/dead-letter``       - list rows that exhausted retries
* ``POST /admin/webhooks/dead-letter/{id}/retry`` - re-queue a dead-letter row
* ``GET /admin/webhooks/outbox/stats``      - counts by status
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import User, WebhookOutbox
from app.workers.webhooks_tasks import manual_retry

router = APIRouter()


class WebhookOutboxRow(BaseModel):
    id: int
    event_type: str
    target_url: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    last_error: str | None
    last_response_code: int | None
    created_at: datetime
    delivered_at: datetime | None
    dead_lettered_at: datetime | None

    class Config:
        from_attributes = True


@router.get("/admin/webhooks/outbox", response_model=list[WebhookOutboxRow])
def list_outbox(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    status_filter: Literal["pending", "sending", "delivered", "dead_letter"] | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[WebhookOutbox]:
    stmt = select(WebhookOutbox).order_by(WebhookOutbox.created_at.desc())
    if status_filter:
        stmt = stmt.where(WebhookOutbox.status == status_filter)
    if event_type:
        stmt = stmt.where(WebhookOutbox.event_type == event_type)
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/admin/webhooks/dead-letter", response_model=list[WebhookOutboxRow])
def list_dead_letter(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[WebhookOutbox]:
    stmt = (
        select(WebhookOutbox)
        .where(WebhookOutbox.status == "dead_letter")
        .order_by(WebhookOutbox.dead_lettered_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


@router.post(
    "/admin/webhooks/dead-letter/{row_id}/retry",
    response_model=WebhookOutboxRow,
)
def retry_dead_letter(
    row_id: int,
    _: User = Depends(require_roles("admin", "gestor")),
) -> WebhookOutbox:
    try:
        row = manual_retry(row_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook outbox row not found")
    return row


@router.get("/admin/webhooks/outbox/stats")
def outbox_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Counts of outbox rows grouped by status, plus oldest pending age."""
    counts = dict(
        db.execute(
            select(WebhookOutbox.status, func.count(WebhookOutbox.id)).group_by(WebhookOutbox.status)
        ).all()
    )
    oldest_pending = db.scalar(
        select(WebhookOutbox.created_at)
        .where(WebhookOutbox.status == "pending")
        .order_by(WebhookOutbox.created_at.asc())
        .limit(1)
    )
    return {
        "counts": {status_name: counts.get(status_name, 0) for status_name in ("pending", "sending", "delivered", "dead_letter")},
        "oldest_pending_age_seconds": (
            (datetime.now(timezone.utc) - oldest_pending).total_seconds()
            if oldest_pending
            else None
        ),
    }
