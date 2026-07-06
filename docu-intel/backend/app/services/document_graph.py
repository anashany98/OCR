from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Document, DocumentEntity, Order


def build_document_graph(db: Session, document_id: int, *, limit: int = 50) -> dict:
    documents: dict[int, Document] = {}
    edges: list[dict] = []

    source = db.get(Document, document_id)
    if not source:
        return {"nodes": [], "edges": []}
    documents[source.id] = source

    budgets = list(db.scalars(select(Budget).where(Budget.document_id == document_id)).all())
    if budgets:
        budget_ids = [b.id for b in budgets]
        orders = list(
            db.scalars(
                select(Order).where(Order.related_budget_id.in_(budget_ids))
            ).all()
        )
        orders_by_budget: dict[int, list[Order]] = {}
        for order in orders:
            orders_by_budget.setdefault(order.related_budget_id, []).append(order)
        for budget in budgets:
            for order in orders_by_budget.get(budget.id, []):
                related = db.get(Document, order.document_id)
                if related:
                    documents[related.id] = related
                    edges.append(
                        {
                            "from_document_id": document_id,
                            "to_document_id": related.id,
                            "relation": "budget_order",
                            "label": budget.budget_number,
                        }
                    )

    references = {
        entity.normalized_value or entity.entity_value
        for entity in db.scalars(
            select(DocumentEntity).where(DocumentEntity.document_id == document_id)
        ).all()
        if entity.normalized_value or entity.entity_value
    }
    if references:
        related_entities = list(
            db.scalars(
                select(DocumentEntity)
                .where(DocumentEntity.document_id != document_id)
                .where(DocumentEntity.normalized_value.in_(references))
                .limit(limit)
            ).all()
        )
        for entity in related_entities:
            related = db.get(Document, entity.document_id)
            if related:
                documents[related.id] = related
                edges.append(
                    {
                        "from_document_id": document_id,
                        "to_document_id": related.id,
                        "relation": "shared_reference",
                        "label": entity.normalized_value or entity.entity_value,
                    }
                )

    return {
        "nodes": [
            {
                "document_id": document.id,
                "filename": document.original_filename,
                "document_type": document.document_type,
                "status": document.status,
            }
            for document in documents.values()
        ],
        "edges": _deduplicate_edges(edges),
    }


def _deduplicate_edges(edges: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for edge in edges:
        key = (
            edge["from_document_id"],
            edge["to_document_id"],
            edge["relation"],
            edge.get("label"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    return unique
