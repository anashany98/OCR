from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class BudgetScope(Base):
    __tablename__ = "budget_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # A budget code is only meaningful inside its source hierarchy.  Legacy
    # rows intentionally remain unscoped until an audited backfill resolves
    # their context.
    budget_code: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotel_chains.id", ondelete="SET NULL"), index=True
    )
    hotel_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotels.id", ondelete="SET NULL"), index=True
    )
    context_key: Mapped[str | None] = mapped_column(String(320), index=True)
    legacy_unscoped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    documents = relationship("Document", back_populates="budget_scope")
    client_permissions = relationship(
        "ApiClientBudgetScope", back_populates="budget_scope", cascade="all, delete-orphan"
    )


class ApiClientBudgetScope(Base):
    __tablename__ = "api_client_budget_scopes"
    __table_args__ = (
        UniqueConstraint("api_client_id", "budget_scope_id", name="uq_api_client_budget_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_client_id: Mapped[int] = mapped_column(
        ForeignKey("integration_clients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    budget_scope_id: Mapped[int] = mapped_column(
        ForeignKey("budget_scopes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    can_query: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_see_amounts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    api_client = relationship("IntegrationClient")
    budget_scope = relationship("BudgetScope", back_populates="client_permissions")
