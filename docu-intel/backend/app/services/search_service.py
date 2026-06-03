from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock, DocumentChunk, DocumentPage
from app.services.cache import cache_service
from app.services.embeddings import cosine_similarity, embed_text
from app.services.metrics import track_search_latency
from app.services.vector_store import PgvectorStore, _is_postgres


SEARCH_CACHE_TTL = 300


def _make_search_cache_key(query: str, limit: int, filters: dict | None, search_type: str) -> str:
    filter_str = json.dumps(filters or {}, sort_keys=True)
    content = f"{search_type}:{query}:{limit}:{filter_str}"
    return f"search:{hashlib.md5(content.encode()).hexdigest()}"


@dataclass
class SearchResult:
    document_id: int
    original_filename: str
    document_type: str
    status: str
    page_number: int | None
    block_id: int | None
    score: float
    excerpt: str
    ocr_confidence: float | None
    source_type: str = "text"


def _search_result_to_dict(result: SearchResult) -> dict:
    return {
        "document_id": result.document_id,
        "original_filename": result.original_filename,
        "document_type": result.document_type,
        "status": result.status,
        "page_number": result.page_number,
        "block_id": result.block_id,
        "score": result.score,
        "excerpt": result.excerpt,
        "ocr_confidence": result.ocr_confidence,
        "source_type": result.source_type,
    }


def _dict_to_search_result(data: dict) -> SearchResult:
    return SearchResult(**data)


def _escape_ilike_wildcards(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_text(db: Session, query: str, limit: int = 20, filters: dict | None = None) -> list[SearchResult]:
    start = time.perf_counter()
    try:
        normalized = query.strip()
        if not normalized:
            return []
        pattern = f"%{_escape_ilike_wildcards(normalized)}%"

        page_stmt = (
            select(Document, DocumentPage)
            .join(DocumentPage, DocumentPage.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentPage.text.ilike(pattern))
        )
        block_stmt = (
            select(Document, DocumentBlock)
            .join(DocumentBlock, DocumentBlock.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentBlock.text.ilike(pattern))
        )
        page_stmt = _apply_document_filters(page_stmt, filters).limit(limit)
        block_stmt = _apply_document_filters(block_stmt, filters).limit(limit)

        page_rows = db.execute(page_stmt).all()
        block_rows = db.execute(block_stmt).all()

        results: list[SearchResult] = []
        seen: set[tuple[int, int | None, int | None]] = set()
        for document, page in page_rows:
            key = (document.id, page.page_number, None)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                SearchResult(
                    document_id=document.id,
                    original_filename=document.original_filename,
                    document_type=document.document_type,
                    status=document.status,
                    page_number=page.page_number,
                    block_id=None,
                    score=1.0,
                    excerpt=_excerpt(page.text or "", normalized),
                    ocr_confidence=page.ocr_confidence,
                    source_type="text_page",
                )
            )
        for document, block in block_rows:
            key = (document.id, block.page_number, block.id)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                SearchResult(
                    document_id=document.id,
                    original_filename=document.original_filename,
                    document_type=document.document_type,
                    status=document.status,
                    page_number=block.page_number,
                    block_id=block.id,
                    score=1.2,
                    excerpt=_excerpt(block.text or "", normalized),
                    ocr_confidence=block.confidence,
                    source_type="text_block",
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]
    finally:
        track_search_latency(time.perf_counter() - start)


def search_semantic(db: Session, query: str, limit: int = 10, filters: dict | None = None) -> list[SearchResult]:
    start = time.perf_counter()
    try:
        normalized = query.strip()
        if not normalized:
            return []

        cache_key = _make_search_cache_key(normalized, limit, filters, "semantic")
        cached = cache_service.get(cache_key)
        if cached is not None:
            return [_dict_to_search_result(r) for r in cached]

        query_embedding = embed_text(normalized)

        pg = PgvectorStore()
        if _is_postgres(db):
            pg_filters = dict(filters) if filters else {}
            matches = pg.search(db, query_embedding=query_embedding, limit=limit, filters=pg_filters)
            results_sorted = [
                SearchResult(
                    document_id=match.document_id,
                    original_filename=match.original_filename,
                    document_type=match.document_type,
                    status=match.status,
                    page_number=match.page_number,
                    block_id=match.chunk_id,
                    score=match.score,
                    excerpt=_excerpt(match.excerpt, normalized),
                    ocr_confidence=None,
                    source_type="semantic_chunk",
                )
                for match in matches
            ]
            cache_service.set(cache_key, [_search_result_to_dict(r) for r in results_sorted], SEARCH_CACHE_TTL)
            return results_sorted

        # SQLite / other: fallback to Python cosine similarity
        stmt = (
            select(Document, DocumentChunk)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentChunk.chunk_text.is_not(None))
        )
        stmt = _apply_document_filters(stmt, filters).limit(max(limit * 30, 100))
        rows = db.execute(stmt).all()

        results: list[SearchResult] = []
        for document, chunk in rows:
            embedding = _coerce_embedding(chunk.embedding)
            if embedding:
                score = cosine_similarity(query_embedding, embedding)
            else:
                score = _lexical_overlap_score(normalized, chunk.chunk_text)
            if score <= 0.02:
                continue
            results.append(
                SearchResult(
                    document_id=document.id,
                    original_filename=document.original_filename,
                    document_type=document.document_type,
                    status=document.status,
                    page_number=chunk.page_number,
                    block_id=None,
                    score=round(float(score), 6),
                    excerpt=_excerpt(chunk.chunk_text, normalized),
                    ocr_confidence=None,
                    source_type="semantic_chunk",
                )
            )

        results_sorted = sorted(results, key=lambda item: item.score, reverse=True)[:limit]

        cache_service.set(cache_key, [_search_result_to_dict(r) for r in results_sorted], SEARCH_CACHE_TTL)

        return results_sorted
    finally:
        track_search_latency(time.perf_counter() - start)


def search_hybrid(db: Session, query: str, limit: int = 10, filters: dict | None = None) -> list[SearchResult]:
    start = time.perf_counter()
    try:
        cache_key = _make_search_cache_key(query.strip(), limit, filters, "hybrid")
        cached = cache_service.get(cache_key)
        if cached is not None:
            return [_dict_to_search_result(r) for r in cached]

        text_results = search_text(db, query, limit=max(limit, 10), filters=filters)
        semantic_results = search_semantic(db, query, limit=max(limit, 10), filters=filters)

        # Merge with a larger pool so the reranker has enough candidates to work with
        rerank_pool_size = max(limit * 3, 15)
        merged = merge_hybrid_results(text_results, semantic_results, limit=rerank_pool_size)

        # Apply cross-encoder reranker for better precision
        if len(merged) > limit:
            from app.services.reranker import rerank_sync
            merged = rerank_sync(query.strip(), merged, top_k=limit)

        cache_service.set(cache_key, [_search_result_to_dict(r) for r in merged], SEARCH_CACHE_TTL)

        return merged
    finally:
        track_search_latency(time.perf_counter() - start)


def merge_hybrid_results(
    text_results: list[SearchResult],
    semantic_results: list[SearchResult],
    limit: int = 10,
) -> list[SearchResult]:
    merged: dict[tuple[int, int | None, int | None], SearchResult] = {}
    for item in text_results:
        key = (item.document_id, item.page_number, item.block_id)
        merged[key] = replace(item, source_type="hybrid_text", score=item.score * 1.1)
    for item in semantic_results:
        key = (item.document_id, item.page_number, item.block_id)
        if key in merged:
            current = merged[key]
            merged[key] = replace(
                current,
                score=current.score + item.score * 0.75,
                source_type="hybrid_text_semantic",
                excerpt=current.excerpt or item.excerpt,
            )
        else:
            merged[key] = replace(item, source_type="hybrid_semantic", score=item.score * 0.9)
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:limit]


def _excerpt(text: str, query: str, radius: int = 160) -> str:
    lowered = text.lower()
    index = lowered.find(query.lower())
    if index < 0:
        return text[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def _apply_document_filters(stmt, filters: dict | None):
    if not filters:
        return stmt
    budget_scope_id = filters.get("budget_scope_id")
    document_type = filters.get("document_type")
    status = filters.get("status")
    quality_status = filters.get("quality_status")
    extension = filters.get("extension")
    if budget_scope_id:
        stmt = stmt.where(Document.budget_scope_id == int(budget_scope_id))
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if status:
        stmt = stmt.where(Document.status == status)
    if quality_status:
        stmt = stmt.where(Document.quality_status == quality_status)
    if extension:
        clean_extension = str(extension).lower()
        if clean_extension and not clean_extension.startswith("."):
            clean_extension = "." + clean_extension
        stmt = stmt.where(Document.extension == clean_extension)
    return stmt


def _coerce_embedding(value) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    try:
        return [float(item) for item in value.tolist()]
    except AttributeError:
        return [float(item) for item in value]


def _lexical_overlap_score(query: str, text: str) -> float:
    query_terms = {term.lower() for term in query.split() if term.strip()}
    text_terms = {term.lower() for term in text.split() if term.strip()}
    if not query_terms or not text_terms:
        return 0.0
    return len(query_terms & text_terms) / len(query_terms)
