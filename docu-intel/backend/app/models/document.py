from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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
    budget_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True
    )
    file_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    extension: Mapped[str | None] = mapped_column(String(32), index=True)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(50), default="desconocido", nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    quality_status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_flags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[Any | None] = mapped_column(Vector(768), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # A7 - aggregate flag set by the embedding pipeline whenever any
    # chunk for the document lands with ``needs_reembedding=True``;
    # cleared by the periodic re-embed sweep (or by the manual
    # ``/admin/documents/{id}/re-embed`` endpoint) when the chunks
    # are successfully re-embedded. Lets the sweep find candidates
    # without a LEFT JOIN + GROUP BY on every tick.
    needs_reembedding: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    # P0.3 — Pipeline stage tracking
    pipeline_stage: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True,
        comment="Current pipeline stage: probing|text_processing|text_ready|metadata_ready|embedding_pending|searchable|fully_processed|needs_review|failed",
    )
    pages_completed: Mapped[int | None] = mapped_column(Integer, comment="Pages processed so far")
    pages_total: Mapped[int | None] = mapped_column(Integer, comment="Total pages in document")
    text_search_ready: Mapped[bool] = mapped_column(default=False, nullable=False, comment="Text available for lexical search")
    semantic_search_ready: Mapped[bool] = mapped_column(default=False, nullable=False, comment="Embeddings available for semantic search")
    page_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    duplicate_of_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    blocks = relationship("DocumentBlock", back_populates="document", cascade="all, delete-orphan")
    entities = relationship(
        "DocumentEntity", back_populates="document", cascade="all, delete-orphan"
    )
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    jobs = relationship("ExtractionJob", back_populates="document", cascade="all, delete-orphan")
    duplicate_of = relationship("Document", remote_side=[id])
    budget_scope = relationship("BudgetScope", back_populates="documents")
    classification_suggestions = relationship(
        "ClassificationSuggestion",
        foreign_keys="ClassificationSuggestion.document_id",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    access_metadata = relationship(
        "DocumentAccessMetadata",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # Hyper-Extract runs (one row per attempt). Cascade so deleting a
    # document also wipes its extraction history.
    extractions = relationship(
        "DocumentExtraction",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    # Phase 3: one document can appear in multiple paths/budgets
    occurrences = relationship(
        "DocumentOccurrence",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    text: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(1024))
    page_status: Mapped[str] = mapped_column(
        String(40), default="processed", nullable=False, index=True
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    # ``ocr_confidence`` is the raw value reported by the winning engine.
    # The calibrated score is the common decision value used for automatic
    # acceptance and review, including engines (such as VLM OCR) that do not
    # return a native confidence.
    ocr_calibrated_confidence: Mapped[float | None] = mapped_column(Float, index=True)
    ocr_content_kind: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    ocr_decision: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    ocr_decision_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Which engine produced this page's text. NULL for pages that haven't been
    # processed yet. Values: pymupdf | paddleocr | empty
    ocr_engine: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Version of the engine that produced this page (e.g. ``paddleocr-v3.0.0``).
    # Tracked separately from ``ocr_engine`` (which is the engine name) so the
    # periodic re-OCR sweep can find pages produced with a stale engine
    # version and reprocess them automatically.
    ocr_engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False, index=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    document = relationship("Document", back_populates="pages")
    blocks = relationship("DocumentBlock", back_populates="page", cascade="all, delete-orphan")
    ocr_attempts = relationship("OcrAttempt", back_populates="page", cascade="all, delete-orphan")


class OcrAttempt(Base):
    """Immutable evidence for each OCR candidate considered for a page."""

    __tablename__ = "ocr_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    engine: Mapped[str] = mapped_column(String(80), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str | None] = mapped_column(Text)
    raw_confidence: Mapped[float | None] = mapped_column(Float)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    page = relationship("DocumentPage", back_populates="ocr_attempts")


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, index=True)
    block_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    bbox_x1: Mapped[float | None] = mapped_column(Float)
    bbox_y1: Mapped[float | None] = mapped_column(Float)
    bbox_x2: Mapped[float | None] = mapped_column(Float)
    bbox_y2: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_engine: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    document = relationship("Document", back_populates="blocks")
    page = relationship("DocumentPage", back_populates="blocks")

    _ALLOWED_BLOCK_TYPES = frozenset({
        "text", "table", "figure", "header", "footer", "list",
        "doc_title", "reference", "seal", "table_title", "figure_title",
        "table_footnote", "text_region", "formula", "chart", "equation",
        "code", "caption",
    })

    @validates("block_type")
    def _sanitize_block_type(self, key, value):
        v = (value or "text").strip().lower()
        return v if v in self._ALLOWED_BLOCK_TYPES else "text"


class DocumentEntity(Base):
    __tablename__ = "document_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_blocks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    document = relationship("Document", back_populates="entities")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    # EMBEDDING_DIMENSIONS: cambiar este valor requiere migración manual
    # ALTER COLUMN embedding TYPE VECTOR(<nueva_dim>) + rebuild del índice.
    embedding: Mapped[Any | None] = mapped_column(Vector(768), nullable=True)
    embedding_provider_used: Mapped[str | None] = mapped_column(String(80))
    embedding_fallback: Mapped[bool] = mapped_column(default=False, nullable=False)
    needs_reembedding: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    token_count: Mapped[int | None] = mapped_column(Integer)
    # E1 — distinguishes prose chunks from table chunks and
    # headings. The default is ``"text"`` so chunks produced by
    # the old chunker (or by deployments that have not migrated)
    # keep behaving as plain text. Indexed so the retriever can
    # filter ``block_type="table"`` cheaply (planned for E3).
    chunk_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False, index=True)
    # E2 — PostgreSQL ``tsvector`` column generated from
    # ``chunk_text`` via ``to_tsvector('simple', ...)``. We do
    # not declare the generation expression at the ORM level
    # (the migration 0021 owns it) so the SQLAlchemy model is
    # portable to engines other than Postgres. The column is
    # ``nullable=True`` because the generated expression can
    # legally be NULL when ``chunk_text`` is NULL, and a stale
    # row inserted before the column existed would otherwise fail
    # the NOT NULL check on a SELECT.
    tsv: Mapped[Any | None] = mapped_column(
        Text(),
        Computed("to_tsvector('spanish', COALESCE(chunk_text, ''::text))", persisted=True),
        nullable=True,
    )
    # E4 — versioned embedding model. When the operator changes
    # ``EMBEDDING_MODEL`` (e.g. ``bge-m3`` → ``bge-m3-v2``),
    # every chunk whose ``embedding_model_version`` differs from
    # the current setting is a candidate for re-embedding. The
    # periodic re-embed sweep reads this column alongside
    # ``needs_reembedding`` so the admin can see "N chunks need
    # re-embedding because the model changed" in the dashboard.
    embedding_model_version: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    document = relationship("Document", back_populates="chunks")


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(80), default="extract", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    document = relationship("Document", back_populates="jobs")


class ImageAnalysis(Base):
    """Phase 5 — Structured visual analysis of an image.

    Stores multi-label classification, visible text, objects, materials,
    measurements, and per-fact confidence. One row per document.
    """
    __tablename__ = "image_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True, nullable=False,
    )
    occurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_occurrences.id", ondelete="SET NULL"), index=True,
    )
    # Multi-label taxonomy
    labels_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Structured visual facts
    visible_text: Mapped[str | None] = mapped_column(Text)
    objects_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    materials_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    colors_json: Mapped[list[str] | None] = mapped_column(JSON)
    measurements_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    product_refs_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    room_or_zone: Mapped[str | None] = mapped_column(String(300))
    installation_state: Mapped[str | None] = mapped_column(String(100))
    issue_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Sensitive data detection
    sensitive_data_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    # Visual embedding (for similarity search)
    visual_embedding: Mapped[Any | None] = mapped_column(Vector(768), nullable=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # Model metadata
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )

    document = relationship("Document", back_populates="image_analysis")


# Add back_populates for ImageAnalysis on Document
Document.image_analysis = relationship(
    "ImageAnalysis",
    back_populates="document",
    uselist=False,
    cascade="all, delete-orphan",
)
