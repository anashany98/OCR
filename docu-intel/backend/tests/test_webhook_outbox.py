"""Tests for the webhook outbox: enqueue, retry, dead-letter, and manual replay."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base
from app.models import WebhookOutbox
from app.services import webhooks as webhooks_service


@pytest.fixture
def db():
    """In-memory SQLite session, schema created per-test for isolation."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        # Patch the worker's _get_session so deliver_pending_webhooks_task
        # operates on this in-memory DB instead of the real SessionLocal.
        with patch("app.workers.webhooks_tasks._get_session", return_value=session):
            yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# enqueue_webhook
# ---------------------------------------------------------------------------


def test_enqueue_webhook_disabled_when_dsn_empty(db, monkeypatch):
    """If INTEGRATION_WEBHOOK_URL is empty, no row is created."""
    monkeypatch.setattr(settings, "integration_webhook_url", "")
    result = webhooks_service.enqueue_webhook(db, event="document.processed", payload={"x": 1})
    assert result is None
    assert db.query(WebhookOutbox).count() == 0


def test_enqueue_webhook_skips_event_not_in_allowlist(db, monkeypatch):
    """Events not in INTEGRATION_WEBHOOK_EVENTS are not enqueued."""
    monkeypatch.setattr(settings, "integration_webhook_url", "https://example.test/hook")
    monkeypatch.setattr(settings, "integration_webhook_events", ["document.processed"])
    result = webhooks_service.enqueue_webhook(db, event="entity.new_pattern_detected", payload={})
    assert result is None


def test_enqueue_webhook_writes_signed_row(db, monkeypatch):
    """A successful enqueue creates a row with the right fields and an HMAC signature."""
    monkeypatch.setattr(settings, "integration_webhook_url", "https://example.test/hook")
    monkeypatch.setattr(settings, "integration_webhook_secret", "test-secret")
    monkeypatch.setattr(settings, "integration_webhook_events", ["document.processed"])

    result = webhooks_service.enqueue_webhook(
        db,
        event="document.processed",
        payload={"document_id": 42},
        idempotency_key="evt-42",
    )
    db.commit()
    assert result is not None
    assert result.id is not None
    assert result.status == "pending"
    assert result.attempts == 0
    assert result.max_attempts == settings.webhook_outbox_max_attempts
    assert result.target_url == "https://example.test/hook"
    assert result.payload_json == {"event": "document.processed", "payload": {"document_id": 42}}
    assert result.signature_header and result.signature_header.startswith("sha256=")
    assert result.idempotency_key == "evt-42"


# ---------------------------------------------------------------------------
# backoff
# ---------------------------------------------------------------------------


def test_backoff_doubles_with_attempts(monkeypatch):
    """backoff_for_attempt(1) = initial, then doubles, then caps at max."""
    monkeypatch.setattr(settings, "webhook_outbox_initial_backoff_seconds", 30)
    monkeypatch.setattr(settings, "webhook_outbox_max_backoff_seconds", 3600)

    assert webhooks_service.backoff_for_attempt(1) == timedelta(seconds=30)
    assert webhooks_service.backoff_for_attempt(2) == timedelta(seconds=60)
    assert webhooks_service.backoff_for_attempt(3) == timedelta(seconds=120)
    # 30 * 2**10 = 30720s would exceed the 1h cap.
    assert webhooks_service.backoff_for_attempt(11) == timedelta(seconds=3600)


# ---------------------------------------------------------------------------
# delivery worker
# ---------------------------------------------------------------------------


def _seed_pending_row(db, target_url: str = "https://example.test/hook", max_attempts: int = 8) -> WebhookOutbox:
    row = WebhookOutbox(
        event_type="document.processed",
        target_url=target_url,
        payload_json={"event": "document.processed", "payload": {"x": 1}},
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_deliver_pending_marks_delivered_on_2xx(db, monkeypatch):
    """A 2xx response moves the row to status='delivered'."""
    from app.workers.webhooks_tasks import deliver_pending_webhooks_task

    row = _seed_pending_row(db)
    row_id = row.id

    response = httpx.Response(200, request=httpx.Request("POST", row.target_url), json={"ok": True})
    with patch("app.workers.webhooks_tasks.httpx.post", return_value=response):
        result = deliver_pending_webhooks_task()

    assert result == {"attempted": 1, "delivered": 1, "failed": 0, "dead_lettered": 0}
    db.expire_all()
    row = db.get(WebhookOutbox, row_id)
    assert row.status == "delivered"
    assert row.delivered_at is not None
    assert row.last_response_code == 200
    assert row.last_error is None


def test_deliver_pending_schedules_retry_on_5xx(db, monkeypatch):
    """A 5xx response keeps the row pending with a future next_attempt_at."""
    from app.workers.webhooks_tasks import deliver_pending_webhooks_task

    monkeypatch.setattr("app.core.config.settings.webhook_outbox_initial_backoff_seconds", 5)
    row = _seed_pending_row(db)
    row_id = row.id
    original_next = row.next_attempt_at

    response = httpx.Response(503, request=httpx.Request("POST", row.target_url), text="upstream down")
    with patch("app.workers.webhooks_tasks.httpx.post", return_value=response):
        result = deliver_pending_webhooks_task()

    assert result["failed"] == 1
    assert result["delivered"] == 0
    db.expire_all()
    row = db.get(WebhookOutbox, row_id)
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.last_response_code == 503
    assert "upstream down" in (row.last_error or "")
    assert row.next_attempt_at > original_next


def test_deliver_pending_dead_letters_after_max_attempts(db, monkeypatch):
    """Once attempts == max_attempts, the row is moved to status='dead_letter'."""
    from app.workers.webhooks_tasks import deliver_pending_webhooks_task

    row = _seed_pending_row(db, max_attempts=2)
    row.attempts = 1  # one failure already, this tick will be the 2nd
    db.commit()
    row_id = row.id

    response = httpx.Response(500, request=httpx.Request("POST", row.target_url), text="boom")
    with patch("app.workers.webhooks_tasks.httpx.post", return_value=response):
        result = deliver_pending_webhooks_task()

    assert result["dead_lettered"] == 1
    db.expire_all()
    row = db.get(WebhookOutbox, row_id)
    assert row.status == "dead_letter"
    assert row.dead_lettered_at is not None
    assert row.attempts == 2


def test_deliver_pending_handles_network_error(db, monkeypatch):
    """httpx.HTTPError (network down) is treated like a failure with no response code."""
    from app.workers.webhooks_tasks import deliver_pending_webhooks_task

    row = _seed_pending_row(db)
    row_id = row.id

    with patch(
        "app.workers.webhooks_tasks.httpx.post",
        side_effect=httpx.ConnectError("no network"),
    ):
        result = deliver_pending_webhooks_task()

    assert result["failed"] == 1
    db.expire_all()
    row = db.get(WebhookOutbox, row_id)
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.last_response_code is None
    assert "ConnectError" in (row.last_error or "")


def test_deliver_pending_no_rows_is_noop(db):
    """Calling the worker with an empty outbox returns a zero result without raising."""
    from app.workers.webhooks_tasks import deliver_pending_webhooks_task

    result = deliver_pending_webhooks_task()
    assert result == {"attempted": 0, "delivered": 0, "failed": 0, "dead_lettered": 0}


# ---------------------------------------------------------------------------
# manual retry
# ---------------------------------------------------------------------------


def test_manual_retry_resets_dead_letter_to_pending(db):
    from app.workers.webhooks_tasks import manual_retry

    row = _seed_pending_row(db, max_attempts=1)
    row.status = "dead_letter"
    row.dead_lettered_at = datetime.now(timezone.utc)
    row.attempts = 1
    row_id = row.id
    db.commit()

    replayed = manual_retry(row_id)
    assert replayed is not None
    db.expire_all()
    row = db.get(WebhookOutbox, row_id)
    assert row.status == "pending"
    assert row.dead_lettered_at is None


def test_manual_retry_returns_none_for_unknown_id(db):
    from app.workers.webhooks_tasks import manual_retry

    assert manual_retry(999_999) is None
