from __future__ import annotations

from datetime import datetime, timezone, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class ClassificationSuggestion(Base):
    __tablename__ = "classification_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_client_id: Mapped[int | None] = mapped_column(ForeignKey("integration_clients.id", ondelete="SET NULL"), nullable=True, index=True)
    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    suggested_document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    current_document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    pattern_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the suggestion has been pending for longer than
    # ``learning_stale_pending_days``. The auto-reject job uses this to skip
    # rows that are still fresh. NULL means "not yet stale".
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    document = relationship("Document", foreign_keys=[document_id], back_populates="classification_suggestions")
    target_document = relationship("Document", foreign_keys=[target_document_id])
    integration_client = relationship("IntegrationClient")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])


class LearnedPattern(Base):
    __tablename__ = "learned_patterns"
    __table_args__ = (
        UniqueConstraint("pattern_type", "pattern_value", "target_action", name="uq_learned_patterns_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    pattern_value: Mapped[str] = mapped_column(Text, nullable=False)
    target_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("classification_suggestions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    source_suggestion = relationship("ClassificationSuggestion", foreign_keys=[source_suggestion_id])