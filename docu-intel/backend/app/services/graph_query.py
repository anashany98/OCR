"""Read-only Graph RAG queries.

This module is the consumer-side counterpart of
``app.services.graph_extraction``: it walks the relational
catalogue (entities, mentions, relations, evidence) and
serialises the result for the document-detail surface and the
chat agent.

Conventions
-----------
* The traversal is **only** SQL. No graph extension is
  involved: we join ``graph_entities``, ``graph_entity_mentions``,
  ``graph_relations`` and ``graph_relation_evidence`` and walk
  the rows in Python. This keeps the read path consistent with
  the write path (``graph_extraction``) and makes the queries
  portable across PostgreSQL versions.
* The output is bounded (``limit`` parameter) so the document
  view cannot OOM by walking a long evidence chain.
* ``list_relations_for_document`` returns relations in which
  the document participates either as the source or the target
  of an entity mention. This mirrors the legacy
  ``build_document_graph`` semantics: from the operator's
  perspective the document is the centre of the graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    GraphEntity,
    GraphEntityMention,
    GraphRelation,
    GraphRelationEvidence,
)


@dataclass(frozen=True)
class RelationEvidenceRow:
    """One evidence quote that backs a relation."""

    evidence_id: int
    relation_id: int
    document_id: int
    page_number: int | None
    quote: str
    confidence: float | None
    extractor_version: str | None
    created_at: object  # ``datetime``; kept loose to avoid circular imports


@dataclass(frozen=True)
class RelationRow:
    """One relation plus the entities it connects and its evidence."""

    relation_id: int
    relation_type: str
    polarity: str
    confidence: float | None
    status: str
    source_entity_id: int
    source_entity_type: str
    source_entity_value: str
    target_entity_id: int
    target_entity_type: str
    target_entity_value: str
    evidence: list[RelationEvidenceRow]


def _document_mentions(db: Session, document_id: int) -> list[int]:
    """Return the catalogue entity ids that mention ``document_id``."""
    rows = db.execute(
        select(GraphEntityMention.entity_id)
        .where(GraphEntityMention.document_id == document_id)
        .distinct()
    ).all()
    return [int(row[0]) for row in rows]


def list_relations_for_document(
    db: Session, document_id: int, *, limit: int = 50
) -> list[RelationRow]:
    """Return the relations in which ``document_id`` participates.

    The traversal is two-hop at most: we look up the document's
    mentions, then the relations whose source or target is one
    of those entities. The result is deduplicated by
    ``relation_id`` and capped at ``limit`` (default 50, max
    200) so the document view stays bounded.
    """
    if not db.get(Document, document_id):
        return []
    bounded_limit = max(1, min(int(limit), 200))
    entity_ids = _document_mentions(db, document_id)
    if not entity_ids:
        return []
    relations = db.execute(
        select(GraphRelation)
        .where(
            (GraphRelation.source_entity_id.in_(entity_ids))
            | (GraphRelation.target_entity_id.in_(entity_ids))
        )
        .order_by(GraphRelation.id.desc())
        .limit(bounded_limit)
    ).scalars().all()
    if not relations:
        return []
    relation_ids = [int(relation.id) for relation in relations]
    entities = {
        int(entity.id): entity
        for entity in db.scalars(
            select(GraphEntity).where(GraphEntity.id.in_({*entity_ids, *_partner_ids(relations)}))
        ).all()
    }
    evidence_rows = db.execute(
        select(GraphRelationEvidence)
        .where(GraphRelationEvidence.relation_id.in_(relation_ids))
        .order_by(GraphRelationEvidence.id.asc())
    ).scalars().all()
    evidence_by_relation: dict[int, list[GraphRelationEvidence]] = {}
    for row in evidence_rows:
        evidence_by_relation.setdefault(int(row.relation_id), []).append(row)
    result: list[RelationRow] = []
    for relation in relations:
        source = entities.get(int(relation.source_entity_id))
        target = entities.get(int(relation.target_entity_id))
        if source is None or target is None:
            # Should not happen: the relation FKs are enforced.
            continue
        result.append(
            RelationRow(
                relation_id=int(relation.id),
                relation_type=relation.relation_type,
                polarity=relation.polarity,
                confidence=relation.confidence,
                status=relation.status,
                source_entity_id=int(source.id),
                source_entity_type=source.entity_type,
                source_entity_value=source.entity_value,
                target_entity_id=int(target.id),
                target_entity_type=target.entity_type,
                target_entity_value=target.entity_value,
                evidence=[
                    RelationEvidenceRow(
                        evidence_id=int(item.id),
                        relation_id=int(item.relation_id),
                        document_id=int(item.document_id),
                        page_number=item.page_number,
                        quote=item.quote,
                        confidence=item.confidence,
                        extractor_version=item.extractor_version,
                        created_at=item.created_at,
                    )
                    for item in evidence_by_relation.get(int(relation.id), [])
                ],
            )
        )
    return result


def _partner_ids(relations: Iterable[GraphRelation]) -> Iterable[int]:
    """Return the partner entity ids of the given relations (deduplicated)."""
    seen: set[int] = set()
    for relation in relations:
        seen.add(int(relation.source_entity_id))
        seen.add(int(relation.target_entity_id))
    return seen


def list_evidence_quotes(
    db: Session, document_id: int, *, limit: int = 50
) -> list[RelationEvidenceRow]:
    """Return the verbatim evidence quotes that originate from ``document_id``.

    This is the read path the chat agent uses to surface the
    audit-trail behind a relation. The function is intentionally
    read-only and returns rows in stable order (newest first)
    so the chat surface can be paged.
    """
    if not db.get(Document, document_id):
        return []
    bounded_limit = max(1, min(int(limit), 200))
    rows = db.execute(
        select(GraphRelationEvidence)
        .where(GraphRelationEvidence.document_id == document_id)
        .order_by(GraphRelationEvidence.id.desc())
        .limit(bounded_limit)
    ).scalars().all()
    return [
        RelationEvidenceRow(
            evidence_id=int(row.id),
            relation_id=int(row.relation_id),
            document_id=int(row.document_id),
            page_number=row.page_number,
            quote=row.quote,
            confidence=row.confidence,
            extractor_version=row.extractor_version,
            created_at=row.created_at,
        )
        for row in rows
    ]


__all__ = [
    "RelationEvidenceRow",
    "RelationRow",
    "list_evidence_quotes",
    "list_relations_for_document",
]
