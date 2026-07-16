"""SQLAlchemy ORM models for the relational Graph RAG tables.

The schema is owned by migration ``0064_graph_rag_relational``. The
seven tables modelled here back the entity/relation graph described in
``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §3 and are queried
exclusively with standard SQL — no graph extension is involved.

Design notes
------------
* ``GraphEntity`` deduplicates mentions across documents within a
  tenant via ``(tenant_id, normalized_value, entity_type)``. The
  migration enforces uniqueness only when ``normalized_value`` is set
  (partial unique index), so entities that resist normalization can
  still co-exist.
* ``GraphEntityMention`` is the per-chunk/page/block pivot. Exactly
  one of ``document_chunk_id``, ``document_page_id`` or
  ``document_block_id`` should be set in practice; the application
  layer enforces that invariant because SQLAlchemy cannot express
  the XOR cleanly.
* ``GraphRelation`` is keyed on
  ``(source_entity_id, target_entity_id, relation_type)`` so re-running
  an extraction is idempotent via ``ON CONFLICT DO NOTHING``.
* ``GraphRelationEvidence`` stores the verbatim quote(s) that back a
  relation. A relation cannot be marked ``status='verified'`` until it
  has at least one evidence row.
* ``GraphExtractionJob`` is the per-(document, extractor version) run
  record. ``scope_key`` lets the worker distinguish partial runs so a
  crash mid-extraction is recoverable.
* ``GraphExtractionError`` is a separate log so the hot path
  (``status='succeeded'`` jobs) stays free of large error blobs.
* ``GraphReviewQueue`` models the human-review surface for relations
  that did not reach the verification threshold. ``target_type`` is
  either ``'entity'`` or ``'relation'``; ``target_id`` points at the
  corresponding row.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    canonical_label: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(8))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    mention_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    mentions = relationship("GraphEntityMention", back_populates="entity", cascade="all, delete-orphan")
    outgoing_relations = relationship(
        "GraphRelation",
        back_populates="source_entity",
        foreign_keys="GraphRelation.source_entity_id",
        cascade="all, delete-orphan",
    )
    incoming_relations = relationship(
        "GraphRelation",
        back_populates="target_entity",
        foreign_keys="GraphRelation.target_entity_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_graph_entities_tenant_normalized",
            "tenant_id",
            "normalized_value",
            "entity_type",
            unique=True,
            postgresql_where=Text("normalized_value IS NOT NULL"),
        ),
    )


class GraphEntityMention(Base):
    __tablename__ = "graph_entity_mentions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE")
    )
    document_page_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE")
    )
    document_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_blocks.id", ondelete="CASCADE")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    entity = relationship("GraphEntity", back_populates="mentions")


class GraphRelation(Base):
    __tablename__ = "graph_relations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_entity_id: Mapped[int] = mapped_column(
        ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[int] = mapped_column(
        ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    polarity: Mapped[str] = mapped_column(String(20), default="asserted", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="verified", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    source_entity = relationship(
        "GraphEntity", back_populates="outgoing_relations", foreign_keys=[source_entity_id]
    )
    target_entity = relationship(
        "GraphEntity", back_populates="incoming_relations", foreign_keys=[target_entity_id]
    )
    evidence = relationship(
        "GraphRelationEvidence", back_populates="relation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_graph_relations_edge",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            unique=True,
        ),
    )


class GraphRelationEvidence(Base):
    __tablename__ = "graph_relation_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    relation_id: Mapped[int] = mapped_column(
        ForeignKey("graph_relations.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    extractor_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    relation = relationship("GraphRelation", back_populates="evidence")


class GraphExtractionJob(Base):
    __tablename__ = "graph_extraction_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extractor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entities_proposed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relations_proposed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    errors = relationship(
        "GraphExtractionError", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_graph_extraction_jobs_scope",
            "document_id",
            "extractor_version",
            "scope_key",
            unique=True,
        ),
    )


class GraphExtractionError(Base):
    __tablename__ = "graph_extraction_errors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("graph_extraction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    job = relationship("GraphExtractionJob", back_populates="errors")


class GraphReviewQueue(Base):
    __tablename__ = "graph_review_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    submitted_by_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("graph_extraction_jobs.id", ondelete="SET NULL")
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('entity', 'relation')",
            name="ck_graph_review_queue_target_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'escalated')",
            name="ck_graph_review_queue_status",
        ),
    )


__all__ = [
    "GraphEntity",
    "GraphEntityMention",
    "GraphRelation",
    "GraphRelationEvidence",
    "GraphExtractionJob",
    "GraphExtractionError",
    "GraphReviewQueue",
]
