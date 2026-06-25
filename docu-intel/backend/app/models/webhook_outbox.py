"""Transactional outbox for reliable webhook delivery.

The application writes a row to ``webhook_outbox`` in the same database
transaction as the business state change (e.g. pattern activation, document
processed). A separate Celery worker polls the table, signs and sends the
payload, and updates the row with the delivery result. On failure the worker
schedules a retry with exponential backoff; after ``max_attempts`` the row is
moved to ``dead_letter`` for manual inspection and replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# BigInteger primary key with SQLite-friendly Integer fallback so the test
# suite (which uses in-memory SQLite) can still create the table.
_BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class WebhookOutbox(Base):
    __tablename__ = "webhook_outbox"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Status: pending -> sending -> delivered | dead_letter
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signature_header: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
