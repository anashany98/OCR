from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.embeddings import cosine_similarity


@dataclass(frozen=True)
class VectorSearchMatch:
    document_id: int
    original_filename: str
    document_type: str
    status: str
    page_number: int | None
    chunk_id: int
    score: float
    excerpt: str


class PgvectorStore:
    def search(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[VectorSearchMatch]:
        effective_filters = filters or {}
        if _is_postgres(db):
            return self._search_postgres(db, query_embedding=query_embedding, limit=limit, filters=effective_filters)
        return self._search_python_fallback(db, query_embedding=query_embedding, limit=limit, filters=effective_filters)

    def _search_postgres(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
    ) -> list[VectorSearchMatch]:
        clauses = ["d.deleted_at IS NULL", "c.embedding IS NOT NULL"]
        params: dict[str, Any] = {
            "query_embedding": _vector_literal(query_embedding),
            "limit": int(limit),
        }
        if filters.get("budget_scope_id"):
            clauses.append("d.budget_scope_id = :budget_scope_id")
            params["budget_scope_id"] = int(filters["budget_scope_id"])
        if filters.get("document_type"):
            clauses.append("d.document_type = :document_type")
            params["document_type"] = filters["document_type"]
        if filters.get("status"):
            clauses.append("d.status = :status")
            params["status"] = filters["status"]
        sql = text(
            f"""
            SELECT
                d.id AS document_id,
                d.original_filename,
                d.document_type,
                d.status,
                c.page_number,
                c.id AS chunk_id,
                c.chunk_text,
                1 - (c.embedding <=> CAST(:query_embedding AS vector)) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE {" AND ".join(clauses)}
            ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :limit
            """
        )
        rows = db.execute(sql, params).mappings().all()
        return [
            VectorSearchMatch(
                document_id=int(row["document_id"]),
                original_filename=str(row["original_filename"]),
                document_type=str(row["document_type"]),
                status=str(row["status"]),
                page_number=row["page_number"],
                chunk_id=int(row["chunk_id"]),
                score=round(float(row["score"] or 0), 6),
                excerpt=str(row["chunk_text"] or ""),
            )
            for row in rows
        ]

    def _search_python_fallback(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
    ) -> list[VectorSearchMatch]:
        stmt = (
            select(Document, DocumentChunk)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentChunk.chunk_text.is_not(None))
        )
        if filters.get("budget_scope_id"):
            stmt = stmt.where(Document.budget_scope_id == int(filters["budget_scope_id"]))
        if filters.get("document_type"):
            stmt = stmt.where(Document.document_type == filters["document_type"])
        if filters.get("status"):
            stmt = stmt.where(Document.status == filters["status"])
        rows = db.execute(stmt.limit(max(limit * 30, 100))).all()
        matches: list[VectorSearchMatch] = []
        for document, chunk in rows:
            embedding = _coerce_embedding(chunk.embedding)
            if not embedding:
                continue
            score = cosine_similarity(query_embedding, embedding)
            if score <= 0.02:
                continue
            matches.append(
                VectorSearchMatch(
                    document_id=document.id,
                    original_filename=document.original_filename,
                    document_type=document.document_type,
                    status=document.status,
                    page_number=chunk.page_number,
                    chunk_id=chunk.id,
                    score=round(float(score), 6),
                    excerpt=chunk.chunk_text,
                )
            )
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]


class QdrantStore:
    def search(self, *args, **kwargs):
        raise NotImplementedError("QdrantStore is a future adapter; set VECTOR_STORE=pgvector for now")


def _is_postgres(db: Session) -> bool:
    try:
        return db.bind is not None and db.bind.dialect.name == "postgresql"
    except Exception:
        return False


def _coerce_embedding(value) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    try:
        return [float(item) for item in value.tolist()]
    except AttributeError:
        return [float(item) for item in value]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"
