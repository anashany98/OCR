"""Celery worker that drains the ``webhook_outbox`` table.

Runs every ``webhook_outbox_interval_seconds`` (default 30s). Each tick:

1. Picks up to ``webhook_outbox_batch_size`` rows whose ``status='pending'`` and
   ``next_attempt_at <= now``, ordered oldest first.
2. For each row, sets ``status='sending'`` and ``attempts += 1`` so concurrent
   workers don't double-send (composited with ``SELECT ... FOR UPDATE SKIP
   LOCKED`` in the polling query).
3. Sends a signed POST to the receiver with the configured timeout.
4. On 2xx, sets ``status='delivered'`` and ``delivered_at=now``.
5. On any other outcome (network error, 4xx, 5xx) increments ``attempts``,
   records the error, and either schedules the next retry with exponential
   backoff or moves the row to ``status='dead_letter'`` if ``attempts`` has
   reached ``max_attempts``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.database.session import SessionLocal
from app.models import WebhookOutbox
from app.services import webhooks as webhooks_service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_session():
    """Return a DB session. Exposed for tests to override."""
    return SessionLocal()


@celery_app.task(name="app.workers.webhooks_tasks.deliver_pending_webhooks_task")
def deliver_pending_webhooks_task() -> dict:
    """Drain the webhook outbox once. Designed to be called every 30s by Beat."""
    db = _get_session()
    try:
        now = datetime.now(UTC)
        stmt = (
            select(WebhookOutbox)
            .where(WebhookOutbox.status == "pending")
            .where(WebhookOutbox.next_attempt_at <= now)
            .order_by(WebhookOutbox.next_attempt_at.asc())
            .limit(settings.webhook_outbox_batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(db.scalars(stmt).all())
        if not rows:
            return {"attempted": 0, "delivered": 0, "failed": 0, "dead_lettered": 0}

        delivered = 0
        failed = 0
        dead_lettered = 0

        for row in rows:
            # Mark as in-flight so other workers skip it.
            row.status = "sending"
            row.attempts = (row.attempts or 0) + 1
            db.flush()

            try:
                response = httpx.post(
                    row.target_url,
                    json=row.payload_json,
                    headers=_headers(row),
                    timeout=settings.integration_webhook_timeout_seconds,
                )
                row.last_response_code = response.status_code
                if 200 <= response.status_code < 300:
                    row.status = "delivered"
                    row.delivered_at = datetime.now(UTC)
                    row.last_error = None
                    delivered += 1
                else:
                    row.last_error = (
                        response.text[:500] if response.text else f"HTTP {response.status_code}"
                    )
                    _schedule_retry_or_dead_letter(db, row)
                    if row.status == "dead_letter":
                        dead_lettered += 1
                    else:
                        failed += 1
            except httpx.HTTPError as exc:
                row.last_error = f"{type(exc).__name__}: {exc}"[:500]
                row.last_response_code = None
                _schedule_retry_or_dead_letter(db, row)
                if row.status == "dead_letter":
                    dead_lettered += 1
                else:
                    failed += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("webhook_delivery_unexpected row_id=%s", row.id)
                row.last_error = f"unexpected: {type(exc).__name__}: {exc}"[:500]
                _schedule_retry_or_dead_letter(db, row)
                failed += 1

        db.commit()
        return {
            "attempted": len(rows),
            "delivered": delivered,
            "failed": failed,
            "dead_lettered": dead_lettered,
        }
    finally:
        db.close()


def _headers(row: WebhookOutbox) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if row.signature_header:
        headers["X-DocuIntel-Signature"] = row.signature_header
    if row.idempotency_key:
        headers["X-DocuIntel-Idempotency-Key"] = row.idempotency_key
    return headers


def _schedule_retry_or_dead_letter(db, row: WebhookOutbox) -> None:
    """If ``row.attempts`` has reached ``max_attempts``, move to dead_letter.

    Otherwise, set ``status='pending'`` and ``next_attempt_at`` to ``now + backoff``.
    """
    if row.attempts >= row.max_attempts:
        row.status = "dead_letter"
        row.dead_lettered_at = datetime.now(UTC)
        logger.warning(
            "webhook_dead_lettered row_id=%s event=%s attempts=%s",
            row.id,
            row.event_type,
            row.attempts,
        )
    else:
        row.status = "pending"
        row.next_attempt_at = datetime.now(UTC) + webhooks_service.backoff_for_attempt(row.attempts)
        logger.info(
            "webhook_retry_scheduled row_id=%s event=%s attempt=%s next_in=%s",
            row.id,
            row.event_type,
            row.attempts,
            webhooks_service.backoff_for_attempt(row.attempts),
        )


# Manual replay from the admin UI. Sets the row back to pending and resets
# next_attempt_at to now so the next worker tick picks it up.
def manual_retry(row_id: int) -> WebhookOutbox | None:
    db = _get_session()
    try:
        row = db.get(WebhookOutbox, row_id)
        if not row:
            return None
        if row.status not in {"dead_letter", "pending"}:
            raise ValueError(f"Cannot retry row in status '{row.status}'")
        row.status = "pending"
        row.next_attempt_at = datetime.now(UTC)
        row.dead_lettered_at = None
        # attempts is intentionally NOT reset: we keep evidence of how many
        # tries the row has had. The retry still counts towards max_attempts.
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()
