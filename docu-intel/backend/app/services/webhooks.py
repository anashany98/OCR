"""Reliable webhook delivery via the transactional outbox.

Old behaviour
-------------
``emit_integration_webhook`` used to call ``httpx.post`` synchronously from the
request-handling thread. If the receiver was down, the event was logged as a
warning and lost forever.

New behaviour
-------------
1. ``emit_integration_webhook`` writes a row to ``webhook_outbox`` in the same
   DB transaction as the business state change. This is the **transactional
   outbox** pattern: either the event and the state change commit together, or
   both are rolled back.
2. A Celery worker (``app.workers.webhooks_tasks.deliver_pending_webhooks_task``)
   polls the table for due rows, signs the payload, sends the HTTP request,
   and updates the row.
3. On failure the worker increments ``attempts`` and schedules a retry with
   exponential backoff (``initial * 2 ** (attempts-1)`` capped at
   ``webhook_outbox_max_backoff_seconds``).
4. After ``max_attempts`` the row is moved to ``dead_letter`` for manual
   inspection and replay via ``/admin/webhooks/dead-letter/{id}/retry``.

Backwards-compatible convenience functions (``emit_document_needs_review``,
``emit_classification_low_confidence``, ``emit_new_pattern_detected``) keep
their signatures so call sites don't have to change.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import WebhookOutbox

logger = logging.getLogger(__name__)


# Learning loop webhook event names
EVENT_DOCUMENT_NEEDS_REVIEW = "document.needs_review"
EVENT_CLASSIFICATION_LOW_CONFIDENCE = "classification.low_confidence"
EVENT_NEW_PATTERN_DETECTED = "entity.new_pattern_detected"


# ---------------------------------------------------------------------------
# Low-level outbox writer
# ---------------------------------------------------------------------------


def _sign(payload_json_str: str) -> str:
    digest = hmac.new(
        settings.integration_webhook_secret.encode("utf-8"),
        payload_json_str.encode("utf-8"),
        sha256,
    ).hexdigest()
    return f"sha256={digest}"


def enqueue_webhook(
    db: Session,
    *,
    event: str,
    payload: dict[str, Any],
    target_url: str | None = None,
    idempotency_key: str | None = None,
) -> WebhookOutbox | None:
    """Write a webhook event to the outbox in the caller's transaction.

    Returns ``None`` if the event is not enabled or the URL is not configured
    (callers don't need to special-case this; the row simply doesn't exist).
    """
    if not target_url:
        target_url = settings.integration_webhook_url
    if not target_url:
        return None
    if not settings.integration_webhook_events or event not in settings.integration_webhook_events:
        return None

    body = {"event": event, "payload": payload}
    body_json = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    signature = _sign(body_json) if settings.integration_webhook_secret else None

    row = WebhookOutbox(
        event_type=event,
        target_url=target_url,
        payload_json=body,
        signature_header=signature,
        idempotency_key=idempotency_key,
        max_attempts=settings.webhook_outbox_max_attempts,
        next_attempt_at=datetime.now(UTC),
    )
    db.add(row)
    return row


def emit_integration_webhook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Backwards-compatible API: enqueue a webhook in a fresh session.

    Existing call sites use this as a fire-and-forget helper. The new code
    path (``enqueue_webhook``) is preferred for in-transaction semantics.
    """
    from app.database.session import SessionLocal

    if not settings.integration_webhook_url:
        return {"sent": False, "reason": "webhook_not_configured"}
    if not settings.integration_webhook_events or event not in settings.integration_webhook_events:
        return {"sent": False, "reason": "event_disabled"}
    db = SessionLocal()
    try:
        row = enqueue_webhook(db, event=event, payload=payload)
        db.commit()
        return {"sent": True, "queued": True, "id": row.id if row else None}
    except Exception as exc:
        db.rollback()
        logger.warning("integration_webhook_enqueue_failed event=%s error=%s", event, exc)
        return {"sent": False, "reason": str(exc)}
    finally:
        db.close()


def build_webhook_test_payload() -> dict[str, Any]:
    return {
        "event": "docuintel.webhook_test",
        "payload": {
            "message": "Webhook de prueba desde Docu-Intel",
        },
    }


# ---------------------------------------------------------------------------
# High-level helpers used by the rest of the app
# ---------------------------------------------------------------------------


def emit_document_needs_review(
    db: Session | None = None,
    *,
    document_id: int,
    filename: str,
    quality_status: str,
    reason: str,
    budget_scope_id: int | None = None,
) -> dict[str, Any] | WebhookOutbox | None:
    """Emit a webhook when a document enters a state that requires human review.

    If ``db`` is provided, the row is enqueued in that session (preferred).
    If not, falls back to a fresh session for backwards compatibility.
    """
    payload = {
        "document_id": document_id,
        "filename": filename,
        "quality_status": quality_status,
        "reason": reason,
        "budget_scope_id": budget_scope_id,
    }
    if db is not None:
        return enqueue_webhook(db, event=EVENT_DOCUMENT_NEEDS_REVIEW, payload=payload)
    return emit_integration_webhook(EVENT_DOCUMENT_NEEDS_REVIEW, payload)


def emit_classification_low_confidence(
    db: Session | None = None,
    *,
    document_id: int,
    filename: str,
    current_type: str,
    confidence: float,
    threshold: float,
    budget_scope_id: int | None = None,
) -> dict[str, Any] | WebhookOutbox | None:
    """Emit a webhook when classification confidence drops below the threshold."""
    payload = {
        "document_id": document_id,
        "filename": filename,
        "current_document_type": current_type,
        "confidence": confidence,
        "threshold": threshold,
        "budget_scope_id": budget_scope_id,
    }
    if db is not None:
        return enqueue_webhook(db, event=EVENT_CLASSIFICATION_LOW_CONFIDENCE, payload=payload)
    return emit_integration_webhook(EVENT_CLASSIFICATION_LOW_CONFIDENCE, payload)


def emit_new_pattern_detected(
    db: Session | None = None,
    *,
    pattern_id: int,
    pattern_type: str,
    pattern_value: str,
    target_class: str | None,
    target_action: str,
    applied_count: int = 0,
) -> dict[str, Any] | WebhookOutbox | None:
    """Emit a webhook when a learned pattern is activated."""
    payload = {
        "pattern_id": pattern_id,
        "pattern_type": pattern_type,
        "pattern_value": pattern_value,
        "target_class": target_class,
        "target_action": target_action,
        "applied_count": applied_count,
    }
    if db is not None:
        return enqueue_webhook(db, event=EVENT_NEW_PATTERN_DETECTED, payload=payload)
    return emit_integration_webhook(EVENT_NEW_PATTERN_DETECTED, payload)


def backoff_for_attempt(attempt: int) -> timedelta:
    """Return the delay to apply before the next retry of a row that just failed.

    ``attempt`` is 1-based: after the first failure we use the initial backoff,
    after the second we double it, etc., capped at ``max_backoff_seconds``.
    """
    initial = max(1, settings.webhook_outbox_initial_backoff_seconds)
    cap = max(initial, settings.webhook_outbox_max_backoff_seconds)
    delay = min(cap, initial * (2 ** max(0, attempt - 1)))
    return timedelta(seconds=delay)
