from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    from sqlalchemy import JSON

    def Vector(_: int):  # type: ignore
        return JSON()

from app.database.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_filename: Mapped[str | None] = mapped_column(String(1024))
    source_path: Mapped[str | None] = mapped_column(String(2048), index=True)
    budget_scope_id: Mapped[int | None] = mapped_column(ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True)
    file_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    extension: Mapped[str | None] = mapped_column(String(32), index=True)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), default="desconocido", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    quality_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_flags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    # A7 - aggregate flag set by the embedding pipeline whenever any
    # chunk for the document lands with ``needs_reembedding=True``;
    # cleared by the periodic re-embed sweep (or by the manual
    # ``/admin/documents/{id}/re-embed`` endpoint) when the chunks
    # are successfully re-embedded. Lets the sweep find candidates
    # without a LEFT JOIN + GROUP BY on every tick.
    needs_reembedding: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    duplicate_of_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    blocks = relationship("DocumentBlock", back_populates="document", cascade="all, delete-orphan")
    entities = relationship("DocumentEntity", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    jobs = relationship("ExtractionJob", back_populates="document", cascade="all, delete-orphan")
    duplicate_of = relationship("Document", remote_side=[id])
    budget_scope = relationship("BudgetScope", back_populates="documents")
    classification_suggestions = relationship("ClassificationSuggestion", foreign_keys="ClassificationSuggestion.document_id", back_populates="document", cascade="all, delete-orphan")
    access_metadata = relationship(
        "DocumentAccessMetadata",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    text: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(1024))
    page_status: Mapped[str] = mapped_column(String(40), default="processed", nullable=False, index=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    # Which engine produced this page's text. NULL for pages that haven't been
    # processed yet. Values: pymupdf | paddleocr | empty
    ocr_engine: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    document = relationship("Document", back_populates="pages")
    blocks = relationship("DocumentBlock", back_populates="page", cascade="all, delete-orphan")


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("document_pages.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, index=True)
    block_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    bbox_x1: Mapped[float | None] = mapped_column(Float)
    bbox_y1: Mapped[float | None] = mapped_column(Float)
    bbox_x2: Mapped[float | None] = mapped_column(Float)
    bbox_y2: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_engine: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    document = relationship("Document", back_populates="blocks")
    page = relationship("DocumentPage", back_populates="blocks")


class DocumentEntity(Base):
    __tablename__ = "document_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_block_id: Mapped[int | None] = mapped_column(ForeignKey("document_blocks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    document = relationship("Document", back_populates="entities")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(1024), nullable=True)
    embedding_provider_used: Mapped[str | None] = mapped_column(String(80))
    embedding_fallback: Mapped[bool] = mapped_column(default=False, nullable=False)
    needs_reembedding: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    document = relationship("Document", back_populates="chunks")


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), default="extract", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    document = relationship("Document", back_populates="jobs")
