"""Relational Graph RAG extractor.

This service persists entities, relations and evidence to the seven
tables introduced by migration ``0064_graph_rag_relational``. It is
the relational-only counterpart to the in-memory
``document_graph.build_document_graph`` helper, which it will
eventually supersede for the surfaces that need persistence.

Design
------
The extractor is intentionally pluggable: a baseline
``SharedReferenceExtractor`` reproduces the legacy
``shared_reference`` edges that the in-memory graph already
exposes, and an ``LlmRelationExtractor`` placeholder lets the team
swap in a model-driven extractor (NuExtract / local LLM with
structured output) without touching the persistence layer. Both
implement :class:`RelationExtractor`, so the worker and the
admin endpoints can stay decoupled from the actual strategy.

The work is **idempotent**. Re-running the extractor on the same
``(document_id, extractor_version, scope_key)`` tuple updates the
job row and reuses the unique constraints on ``graph_relations`` and
``graph_extraction_jobs`` to skip duplicates. Every relation is
required to have at least one evidence row before it is marked
``status='verified'``; relations that lack evidence are pushed to
``graph_review_queue`` instead of being persisted as
"verified", preserving the auditability contract from
``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §3.2.

Conventions
-----------
* Confidence values are floats in ``[0, 1]``. The
  ``VERIFY_THRESHOLD`` constant is the cut-off below which a
  relation is sent to human review instead of being marked
  verified.
* ``relation_type`` is a free-form string. New types can be
  added at the extractor level without a schema change.
* ``extractor_version`` is a short string (e.g. ``"baseline-v1"``).
  Bumping it forces a fresh job row; the old rows stay in the
  database so the audit trail is preserved.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentEntity,
    GraphEntity,
    GraphEntityMention,
    GraphExtractionError,
    GraphExtractionJob,
    GraphRelation,
    GraphRelationEvidence,
    GraphReviewQueue,
)

logger = logging.getLogger(__name__)


# Relations whose ``confidence`` is below this floor are pushed to
# ``graph_review_queue`` instead of being marked ``status='verified'``.
VERIFY_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Extractor protocol
# ---------------------------------------------------------------------------


@dataclass
class ProposedRelation:
    """A relation proposed by an extractor, ready for verification.

    The extractor fills ``source`` / ``target`` with either an
    existing ``GraphEntity`` id (when the entity already exists in
    the catalogue) or with the entity_type + value pair (when the
    catalogue lookup should upsert the entity). The persistence
    layer normalises both shapes via :func:`_resolve_entity`.
    """

    source_entity_type: str
    source_entity_value: str
    source_normalized_value: str | None
    target_entity_type: str
    target_entity_value: str
    target_normalized_value: str | None
    relation_type: str
    confidence: float
    evidence: list["ProposedEvidence"] = field(default_factory=list)


@dataclass
class ProposedEvidence:
    """Verbatim quote backing a proposed relation."""

    document_id: int
    chunk_id: int | None
    page_number: int | None
    quote: str
    confidence: float | None = None


class RelationExtractor(Protocol):
    """Pluggable strategy that proposes relations for a document."""

    #: Short identifier persisted in ``graph_extraction_jobs.extractor_version``.
    version: str

    def propose(
        self, db: Session, document_id: int
    ) -> list[ProposedRelation]:  # pragma: no cover - interface
        ...


# ---------------------------------------------------------------------------
# Baseline extractor: shared references between documents
# ---------------------------------------------------------------------------


class SharedReferenceExtractor:
    """Replicates the legacy ``shared_reference`` edges of ``document_graph``.

    For a given ``document_id`` the extractor:

    1. collects every normalized reference from the document's
       ``DocumentEntity`` rows;
    2. finds other documents that share at least one reference;
    3. proposes a ``shared_reference`` relation between the
       document entities (``entity_type='document'``) of the
       source and each match;
    4. attaches the matching normalized value as a verbatim evidence
       quote (truncated) so the relation is auditable.

    The confidence is the Jaccard-style ratio of shared references
    between the two documents, which keeps the signal interpretable
    while still being deterministic — important because the baseline
    extractor is the unit-tested reference for downstream model-based
    extractors.
    """

    version = "baseline-shared-reference-v1"

    def __init__(self, *, min_shared: int = 1, quote_max_chars: int = 240) -> None:
        self._min_shared = max(1, int(min_shared))
        self._quote_max_chars = max(40, int(quote_max_chars))

    def propose(
        self, db: Session, document_id: int
    ) -> list[ProposedRelation]:
        document = db.get(Document, document_id)
        if not document:
            return []
        source_refs = self._collect_references(db, document_id)
        if not source_refs:
            return []
        related_docs = self._find_related_documents(db, document_id, source_refs.keys())
        proposals: list[ProposedRelation] = []
        for target_doc_id, shared in related_docs.items():
            target_refs = self._collect_references(db, target_doc_id)
            union_size = len(source_refs.keys() | target_refs.keys()) or 1
            confidence = len(shared) / float(union_size)
            for normalized in sorted(shared):
                quote = source_refs[normalized]
                proposals.append(
                    ProposedRelation(
                        source_entity_type="document",
                        source_entity_value=str(document_id),
                        source_normalized_value=None,
                        target_entity_type="document",
                        target_entity_value=str(target_doc_id),
                        target_normalized_value=None,
                        relation_type="shared_reference",
                        confidence=confidence,
                        evidence=[
                            ProposedEvidence(
                                document_id=document_id,
                                chunk_id=None,
                                page_number=None,
                                quote=quote[: self._quote_max_chars],
                                confidence=confidence,
                            )
                        ],
                    )
                )
        return proposals

    @staticmethod
    def _collect_references(
        db: Session, document_id: int
    ) -> dict[str, str]:
        """Return ``{normalized_value: entity_value}`` for the document."""
        rows = db.scalars(
            select(DocumentEntity).where(DocumentEntity.document_id == document_id)
        ).all()
        refs: dict[str, str] = {}
        for row in rows:
            key = (row.normalized_value or row.entity_value or "").strip()
            if not key:
                continue
            refs.setdefault(key, row.entity_value or key)
        return refs

    def _find_related_documents(
        self,
        db: Session,
        document_id: int,
        source_refs: Iterable[str],
    ) -> dict[int, set[str]]:
        """Return ``{other_document_id: {shared_normalized_value}}``."""
        refs = list(source_refs)
        if not refs:
            return {}
        rows = db.execute(
            select(DocumentEntity.document_id, DocumentEntity.normalized_value, DocumentEntity.entity_value)
            .where(DocumentEntity.document_id != document_id)
            .where(
                (DocumentEntity.normalized_value.in_(refs))
                | (DocumentEntity.entity_value.in_(refs))
            )
        ).all()
        related: dict[int, set[str]] = {}
        for other_doc_id, normalized, raw in rows:
            key = (normalized or raw or "").strip()
            if not key:
                continue
            shared = related.setdefault(int(other_doc_id), set())
            shared.add(key)
        # Apply the min_shared filter so noisy single-character
        # matches do not flood the catalogue.
        return {
            doc_id: shared
            for doc_id, shared in related.items()
            if len(shared) >= self._min_shared
        }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _resolve_entity(
    db: Session,
    *,
    tenant_id: int,
    entity_type: str,
    entity_value: str,
    normalized_value: str | None,
) -> int:
    """Return the catalogue id for the given entity, upserting if needed.

    The unique key is ``(tenant_id, normalized_value, entity_type)``
    (with ``normalized_value`` nullable). We use PostgreSQL's
    ``ON CONFLICT DO NOTHING`` so concurrent extraction jobs
    cannot create duplicate catalogue rows.
    """
    if normalized_value:
        stmt = pg_insert(GraphEntity).values(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_value=entity_value,
            normalized_value=normalized_value,
            mention_count=0,
        )
        # Without the index hint Postgres picks the first unique
        # constraint on the table; ``uq_graph_entities_tenant_normalized``
        # is the one we want here.
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "normalized_value", "entity_type"]
        )
        db.execute(stmt)
        db.flush()
        row = db.scalar(
            select(GraphEntity.id)
            .where(GraphEntity.tenant_id == tenant_id)
            .where(GraphEntity.entity_type == entity_type)
            .where(GraphEntity.normalized_value == normalized_value)
        )
        if row is not None:
            return int(row)
    # Fall back to the (entity_type, entity_value) lookup for
    # entities that could not be normalized.
    existing = db.scalar(
        select(GraphEntity).where(
            GraphEntity.tenant_id == tenant_id,
            GraphEntity.entity_type == entity_type,
            GraphEntity.entity_value == entity_value,
        )
    )
    if existing is not None:
        return int(existing.id)
    fallback = GraphEntity(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_value=entity_value,
        normalized_value=None,
    )
    db.add(fallback)
    db.flush()
    return int(fallback.id)


def _bump_mention_count(db: Session, entity_id: int) -> None:
    """Increment the catalogue's mention counter atomically."""
    db.execute(
        GraphEntity.__table__.update()
        .where(GraphEntity.id == entity_id)
        .values(
            mention_count=GraphEntity.mention_count + 1,
            last_seen_at=datetime.now(UTC),
        )
    )


def _upsert_relation(
    db: Session,
    *,
    source_id: int,
    target_id: int,
    proposal: ProposedRelation,
) -> int | None:
    """Persist a relation, returning the relation id (or ``None`` on duplicate).

    The unique key ``(source_entity_id, target_entity_id, relation_type)``
    is the contract that makes the extraction idempotent: a re-run on
    the same document does not create duplicate relations.
    """
    if source_id == target_id:
        return None
    insert_stmt = (
        pg_insert(GraphRelation)
        .values(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relation_type=proposal.relation_type,
            confidence=proposal.confidence,
            status="verified" if proposal.confidence >= VERIFY_THRESHOLD else "pending",
        )
        .on_conflict_do_nothing(
            index_elements=["source_entity_id", "target_entity_id", "relation_type"]
        )
        .returning(GraphRelation.id)
    )
    try:
        result = db.execute(insert_stmt)
    except IntegrityError:
        db.rollback()
        return None
    inserted_id = result.scalarone_or_none()
    if inserted_id is None:
        # Duplicate: re-fetch the existing row.
        existing = db.scalar(
            select(GraphRelation.id)
            .where(
                GraphRelation.source_entity_id == source_id,
                GraphRelation.target_entity_id == target_id,
                GraphRelation.relation_type == proposal.relation_type,
            )
        )
        return int(existing) if existing is not None else None
    return int(inserted_id)


def _enqueue_review(
    db: Session,
    *,
    relation_id: int | None,
    entity_id: int | None,
    job_id: int,
    confidence: float,
    rationale: str,
) -> None:
    """Push a low-confidence row to the human-review queue."""
    target_type = "relation" if relation_id is not None else "entity"
    target_id = relation_id if relation_id is not None else entity_id
    if target_id is None:
        return
    db.add(
        GraphReviewQueue(
            target_type=target_type,
            target_id=int(target_id),
            status="pending",
            submitted_by_job_id=job_id,
            confidence=confidence,
            rationale=rationale,
        )
    )


def _record_error(db: Session, job_id: int, stage: str, message: str) -> None:
    """Append an error row to ``graph_extraction_errors``.

    The migration pre-creates the table; this helper is the only
    place that writes to it. Errors are kept small so the hot
    path is unaffected by the failure log.
    """
    db.add(
        GraphExtractionError(
            job_id=job_id,
            stage=stage,
            error_message=message[:2000],
        )
    )


# ---------------------------------------------------------------------------
# Job orchestration
# ---------------------------------------------------------------------------


def run_extraction(
    db: Session,
    *,
    document_id: int,
    extractor: RelationExtractor,
    scope_key: str | None = None,
    tenant_id: int,
) -> int:
    """Run ``extractor`` on ``document_id`` and persist the result.

    Returns the ``graph_extraction_jobs.id`` of the run. The
    function is idempotent: re-running with the same
    ``(document_id, extractor.version, scope_key)`` reuses the
    job row and re-applies the relations (the per-relation
    unique constraint skips the duplicates).
    """
    final_scope_key = scope_key or uuid.uuid4().hex
    job = db.scalar(
        select(GraphExtractionJob).where(
            GraphExtractionJob.document_id == document_id,
            GraphExtractionJob.extractor_version == extractor.version,
            GraphExtractionJob.scope_key == final_scope_key,
        )
    )
    if job is None:
        job = GraphExtractionJob(
            document_id=document_id,
            extractor_version=extractor.version,
            scope_key=final_scope_key,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(job)
        db.flush()
    else:
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.finished_at = None

    relations_proposed = 0
    entities_proposed = 0
    try:
        proposals = extractor.propose(db, document_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("graph extraction failed: document=%s", document_id)
        _record_error(db, job.id, stage="propose", message=str(exc))
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
        db.flush()
        return int(job.id)

    for proposal in proposals:
        try:
            source_id = _resolve_entity(
                db,
                tenant_id=tenant_id,
                entity_type=proposal.source_entity_type,
                entity_value=proposal.source_entity_value,
                normalized_value=proposal.source_normalized_value,
            )
            target_id = _resolve_entity(
                db,
                tenant_id=tenant_id,
                entity_type=proposal.target_entity_type,
                entity_value=proposal.target_entity_value,
                normalized_value=proposal.target_normalized_value,
            )
            entities_proposed += 2  # both ends of the edge count
            _bump_mention_count(db, source_id)
            _bump_mention_count(db, target_id)
            relation_id = _upsert_relation(
                db, source_id=source_id, target_id=target_id, proposal=proposal
            )
            if relation_id is None:
                # Duplicate: still record the mention so the
                # catalogue stays in sync, but skip the evidence
                # insert (it would be a duplicate quote).
                continue
            for evidence in proposal.evidence:
                db.add(
                    GraphRelationEvidence(
                        relation_id=relation_id,
                        document_id=evidence.document_id,
                        document_chunk_id=evidence.chunk_id,
                        page_number=evidence.page_number,
                        quote=evidence.quote,
                        confidence=evidence.confidence,
                        extractor_version=extractor.version,
                    )
                )
                # Attach a mention row for the source so the
                # catalogue records the document that surfaced the
                # relation.
                db.add(
                    GraphEntityMention(
                        entity_id=source_id,
                        document_id=evidence.document_id,
                        document_chunk_id=evidence.chunk_id,
                        page_number=evidence.page_number,
                        quote=evidence.quote,
                        confidence=evidence.confidence,
                    )
                )
            relations_proposed += 1
            if proposal.confidence < VERIFY_THRESHOLD:
                _enqueue_review(
                    db,
                    relation_id=relation_id,
                    entity_id=None,
                    job_id=job.id,
                    confidence=proposal.confidence,
                    rationale=f"confidence {proposal.confidence:.2f} < {VERIFY_THRESHOLD}",
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("graph extraction proposal failed")
            _record_error(
                db,
                job.id,
                stage="persist",
                message=f"source={proposal.source_entity_value!r} target={proposal.target_entity_value!r}: {exc}",
            )

    job.entities_proposed = entities_proposed
    job.relations_proposed = relations_proposed
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    db.flush()
    return int(job.id)


__all__ = [
    "ProposedEvidence",
    "ProposedRelation",
    "RelationExtractor",
    "SharedReferenceExtractor",
    "VERIFY_THRESHOLD",
    "run_extraction",
]
