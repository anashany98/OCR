"""Search tools for the AI agent.

Used to perform text, semantic, and hybrid searches across documents.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentEntity
from app.services.search_service import search_hybrid as run_hybrid_search


def search_entities(db: Session, entity_type: str, value: str):
    return list(
        db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.entity_value.ilike(f"%{value}%"))
            .limit(50)
        ).all()
    )


def hybrid_search(db: Session, query: str, filters: dict | None = None):
    return run_hybrid_search(
        db, query, filters=(filters or {}), limit=(filters or {}).get("limit", 10)
    )
