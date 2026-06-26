"""Hyper-Extract — SQLAlchemy persistence.

Stores one row per (document, run) attempt. The structured payload is
kept in JSON columns so the schema does not need to evolve when we add
new document types or field names; the typed interpretation lives in
:mod:`app.services.hyperextract`.

The table is intentionally small and append-only — it never replaces
the OCR rows, it just records what Hyper-Extract produced on top of
them. Foreign keys cascade on delete so removing a document also wipes
its extraction history.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class DocumentExtraction(Base):
    """A single Hyper-Extract run against a document."""

    __tablename__ = "document_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Free-form so we can keep template names ("factura", "albaran",
    # "contrato", "presupuesto") plus future types without a migration.
    document_type: Mapped[str | None] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    # ``pending`` | ``success`` | ``failed`` | ``disabled`` | ``skipped``
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    entities_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    relations_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Truncated raw payload (first 4 KB) — kept only when
    # ``hyperextract_persist_raw_output`` is true so we can audit and
    # replay runs without bloating the table.
    raw_output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    document = relationship("Document", back_populates="extractions")

    def to_envelope(self) -> dict[str, Any]:
        """Render the canonical envelope (matches the service output).

        Useful when the route returns the stored row back to the API
        caller without re-running the extraction.
        """
        return {
            "enabled": True,
            "status": self.status,
            "document_id": self.document_id,
            "document_type": self.document_type,
            "fields": self.fields_json or {},
            "entities": self.entities_json or [],
            "relations": self.relations_json or [],
            "raw_output": self.raw_output_json or {},
            "warnings": self.warnings_json or [],
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms or 0,
            "error_message": self.error_message,
        }
