"""Phase 3 — Hierarchical project model and document occurrences.

Brand / Hotel already exist in tenant.py. This module adds:
  - Project: ties a brand+hotel to a set of budgets and documents.
  - DocumentOccurrence: one row per (document, source_path) appearance.
  - DocumentBudgetLink: explicit link between a document and a budget scope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Project(Base):
    """A project groups budgets, documents and people under a brand/hotel."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("hotel_chains.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    hotel_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotels.id", ondelete="SET NULL"), index=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    primary_budget_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True,
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    manager_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )

    brand = relationship("HotelChain", foreign_keys=[brand_id])
    hotel = relationship("Hotel", foreign_keys=[hotel_id])
    primary_budget_scope = relationship("BudgetScope", foreign_keys=[primary_budget_scope_id])
    occurrences = relationship("DocumentOccurrence", back_populates="project")


class DocumentOccurrence(Base):
    """Each row is one appearance of a document in a specific path/budget.

    The same physical file (same SHA) can have multiple occurrences across
    different budgets and projects without duplicating bytes.
    """
    __tablename__ = "document_occurrences"
    __table_args__ = (
        UniqueConstraint("source_root", "source_path", name="uq_occurrence_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_root: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("hotel_chains.id", ondelete="SET NULL"), index=True, nullable=False,
    )
    hotel_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotels.id", ondelete="SET NULL"), index=True,
    )
    budget_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True,
    )
    category: Mapped[str] = mapped_column(String(100), default="otros", nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )

    document = relationship("Document", back_populates="occurrences")
    project = relationship("Project", back_populates="occurrences")
    brand = relationship("HotelChain", foreign_keys=[brand_id])
    hotel = relationship("Hotel", foreign_keys=[hotel_id])
    budget_scope = relationship("BudgetScope", foreign_keys=[budget_scope_id])


class DocumentBudgetLink(Base):
    """Explicit link between a document and a budget scope with provenance."""
    __tablename__ = "document_budget_links"
    __table_args__ = (
        UniqueConstraint("document_id", "budget_scope_id", name="uq_doc_budget_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    occurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_occurrences.id", ondelete="SET NULL"), index=True,
    )
    budget_scope_id: Mapped[int] = mapped_column(
        ForeignKey("budget_scopes.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(30), default="folder", nullable=False,
    )  # folder | content | filename | relation | manual
    extracted_code: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="verified", nullable=False, index=True,
    )  # verified | folder_only | content_only | conflict
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False,
    )

    document = relationship("Document")
    occurrence = relationship("DocumentOccurrence")
    budget_scope = relationship("BudgetScope")
