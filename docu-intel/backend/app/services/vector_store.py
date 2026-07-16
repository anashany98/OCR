from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, DocumentChunk
from app.services.embeddings import cosine_similarity


@dataclass(frozen=True)
class VectorSearchMatch:
    document_id: int
    original_filename: str
    document_type: str
    status: str
    page_number: int | None
    chunk_id: int | None
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
        # Vector retrieval is a low-level primitive and must never turn an
        # omitted tenant/budget filter into a corpus-wide nearest-neighbour
        # query.  Callers must establish the concrete budget scope before
        # they reach this adapter.
        has_budget_scope = effective_filters.get("budget_scope_id") is not None
        has_project_scope = effective_filters.get("project_id") is not None
        # ``_allow_global_semantic_search`` is an internal-only capability
        # injected by search_service after it has resolved an administrator
        # access scope.  It is deliberately not a public API filter: ordinary
        # callers must still provide a concrete budget scope, preventing a
        # tenant-wide nearest-neighbour query by accident.
        allow_verified_admin_global = effective_filters.get("_allow_global_semantic_search") is True
        if not has_budget_scope and not has_project_scope and not allow_verified_admin_global:
            raise ValueError("PgvectorStore.search requires budget_scope_id or project_id filter")
        if _is_postgres(db):
            return self._search_postgres(
                db, query_embedding=query_embedding, limit=limit, filters=effective_filters
            )
        return self._search_python_fallback(
            db, query_embedding=query_embedding, limit=limit, filters=effective_filters
        )

    def _search_postgres(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
    ) -> list[VectorSearchMatch]:
        # PG-HNSW-01: per-transaction override. ``SET LOCAL`` is scoped to the
        # current SQLAlchemy transaction and reverts on commit/rollback, so
        # the value never leaks to other sessions/connections in the pool.
        _apply_hnsw_ef_search(db)
        clauses = ["d.deleted_at IS NULL", "c.embedding IS NOT NULL"]
        params: dict[str, Any] = {
            "query_embedding": _vector_literal(query_embedding),
            "limit": int(limit),
        }
        if filters.get("budget_scope_id"):
            clauses.append("d.budget_scope_id = :budget_scope_id")
            params["budget_scope_id"] = int(filters["budget_scope_id"])
        if filters.get("project_id"):
            clauses.append(
                "EXISTS (SELECT 1 FROM document_occurrences o "
                "WHERE o.document_id = d.id AND o.project_id = :project_id)"
            )
            params["project_id"] = int(filters["project_id"])
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
        if filters.get("project_id"):
            from app.models.project import DocumentOccurrence

            stmt = stmt.where(
                select(DocumentOccurrence.id)
                .where(DocumentOccurrence.document_id == Document.id)
                .where(DocumentOccurrence.project_id == int(filters["project_id"]))
                .exists()
            )
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

    def search_documents(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[VectorSearchMatch]:
        """Document-level retrieval: match the whole-document embedding.

        Unlike :meth:`search` (which ranks individual chunks), this ranks
        whole documents by their single ``Document.embedding``. It improves
        thematic recall for queries whose answer spans the document but no
        single chunk is a strong standalone match. The two strategies are
        fused downstream via RRF (see ``search_service``).
        """
        effective_filters = filters or {}
        has_budget_scope = effective_filters.get("budget_scope_id") is not None
        has_project_scope = effective_filters.get("project_id") is not None
        allow_verified_admin_global = effective_filters.get("_allow_global_semantic_search") is True
        if not has_budget_scope and not has_project_scope and not allow_verified_admin_global:
            raise ValueError(
                "PgvectorStore.search_documents requires budget_scope_id or project_id filter"
            )
        if _is_postgres(db):
            return self._search_documents_postgres(
                db, query_embedding=query_embedding, limit=limit, filters=effective_filters
            )
        return self._search_documents_python(
            db, query_embedding=query_embedding, limit=limit, filters=effective_filters
        )

    def _search_documents_postgres(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
    ) -> list[VectorSearchMatch]:
        # PG-HNSW-01: same per-transaction override as ``_search_postgres``.
        # Applied here too so document-level retrieval honours the same knob.
        _apply_hnsw_ef_search(db)
        clauses = ["d.deleted_at IS NULL", "d.embedding IS NOT NULL"]
        params: dict[str, Any] = {
            "query_embedding": _vector_literal(query_embedding),
            "limit": int(limit),
        }
        if filters.get("budget_scope_id"):
            clauses.append("d.budget_scope_id = :budget_scope_id")
            params["budget_scope_id"] = int(filters["budget_scope_id"])
        if filters.get("project_id"):
            clauses.append(
                "EXISTS (SELECT 1 FROM document_occurrences o "
                "WHERE o.document_id = d.id AND o.project_id = :project_id)"
            )
            params["project_id"] = int(filters["project_id"])
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
                (
                    SELECT string_agg(p.text, chr(10) ORDER BY p.page_number)
                    FROM document_pages p
                    WHERE p.document_id = d.id
                ) AS doc_text,
                1 - (d.embedding <=> CAST(:query_embedding AS vector)) AS score
            FROM documents d
            WHERE {" AND ".join(clauses)}
            ORDER BY d.embedding <=> CAST(:query_embedding AS vector)
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
                page_number=None,
                chunk_id=None,
                score=round(float(row["score"] or 0), 6),
                excerpt=_doc_excerpt(row.get("doc_text")),
            )
            for row in rows
        ]

    def _search_documents_python(
        self,
        db: Session,
        *,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
    ) -> list[VectorSearchMatch]:
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.embedding.is_not(None))
        )
        if filters.get("budget_scope_id"):
            stmt = stmt.where(Document.budget_scope_id == int(filters["budget_scope_id"]))
        if filters.get("project_id"):
            from app.models.project import DocumentOccurrence

            stmt = stmt.where(
                select(DocumentOccurrence.id)
                .where(DocumentOccurrence.document_id == Document.id)
                .where(DocumentOccurrence.project_id == int(filters["project_id"]))
                .exists()
            )
        if filters.get("document_type"):
            stmt = stmt.where(Document.document_type == filters["document_type"])
        if filters.get("status"):
            stmt = stmt.where(Document.status == filters["status"])
        docs = db.execute(stmt.limit(max(limit * 30, 100))).scalars().all()
        matches: list[VectorSearchMatch] = []
        for document in docs:
            embedding = _coerce_embedding(document.embedding)
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
                    page_number=None,
                    chunk_id=None,
                    score=round(float(score), 6),
                    excerpt=_doc_excerpt(None),
                )
            )
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]


class QdrantStore:
    def search(self, *args, **kwargs):
        raise NotImplementedError(
            "QdrantStore is a future adapter; set VECTOR_STORE=pgvector for now"
        )


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
    expected_dimensions = int(settings.embedding_dimensions or 768)
    if len(values) != expected_dimensions:
        raise ValueError(
            f"Query embedding dimension mismatch: got {len(values)}, expected "
            f"{expected_dimensions}. Check EMBEDDING_MODEL/EMBEDDING_DIMENSIONS "
            "before querying pgvector."
        )
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _doc_excerpt(text: str | None, max_chars: int = 300) -> str:
    """Truncate a whole-document text to a display excerpt."""
    if not text:
        return ""
    return text[:max_chars]


# PG-HNSW-01: clamp values produced by Pydantic out of an unexpected
# migration path (e.g. tests reading ``settings.search_hnsw_ef_search``
# from a different Settings instance). The Settings model already enforces
# ``ge=20, le=200`` at construction time, so this clamp is defensive only.
_HNSW_EF_SEARCH_MIN = 20
_HNSW_EF_SEARCH_MAX = 200


def _apply_hnsw_ef_search(db: Session) -> None:
    """Apply ``SET LOCAL hnsw.ef_search`` to the current transaction.

    pgvector exposes the HNSW ``ef_search`` parameter as a session-level
    GUC. ``SET LOCAL`` confines the override to the current SQLAlchemy
    transaction (which the upcoming ``SELECT`` joins automatically),
    so neighbouring requests in the same connection pool are unaffected.

    The value comes from :attr:`Settings.search_hnsw_ef_search` and is
    clamped to the validated range ``[20, 200]``. See
    ``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §2.3 for the rationale.
    """
    raw_value = int(getattr(settings, "search_hnsw_ef_search", 40))
    clamped = max(_HNSW_EF_SEARCH_MIN, min(_HNSW_EF_SEARCH_MAX, raw_value))
    if clamped != raw_value:
        # Surface a warning so operators notice silent clamping.
        from logging import getLogger

        getLogger(__name__).warning(
            "search_hnsw_ef_search=%s fuera de rango; clampeado a %s",
            raw_value,
            clamped,
        )
    db.execute(text(f"SET LOCAL hnsw.ef_search = {clamped}"))
