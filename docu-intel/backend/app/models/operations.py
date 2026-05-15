from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class WatchedFile(Base):
    __tablename__ = "watched_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(2048), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="detected", nullable=False, index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mtime_epoch: Mapped[float | None] = mapped_column(Float)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("extraction_jobs.id", ondelete="SET NULL"), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    document = relationship("Document")
    job = relationship("ExtractionJob")
    events = relationship("IngestionEvent", back_populates="watched_file", cascade="all, delete-orphan")


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_path: Mapped[str | None] = mapped_column(String(2048), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("extraction_jobs.id", ondelete="SET NULL"), index=True)
    watched_file_id: Mapped[int | None] = mapped_column(ForeignKey("watched_files.id", ondelete="SET NULL"), index=True)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    document = relationship("Document")
    job = relationship("ExtractionJob")
    watched_file = relationship("WatchedFile", back_populates="events")
