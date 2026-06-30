from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, DocumentBlock, DocumentChunk, DocumentPage
from app.services.cache import cache_service
from app.services.embeddings import cosine_similarity, embed_query_text
from app.services.metrics import track_search_latency
from app.services.vector_store import PgvectorStore, _is_postgres

logger = logging.getLogger(__name__)

# Shared thread pool for parallel search strategies.
_search_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="search")


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
    # Relative path the document was uploaded from (e.g.
    # "presupuestos/245745/foo.pdf"). Helps the IA agent disambiguate
    # documents that share a name but live in different folders.
    source_path: str | None = None


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
        "source_path": result.source_path,
    }


def _dict_to_search_result(data: dict) -> SearchResult:
    return SearchResult(**data)


def _escape_ilike_wildcards(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_text(
    db: Session,
    query: str,
    limit: int = 20,
    filters: dict | None = None,
    access_scope=None,
) -> list[SearchResult]:
    """ILIKE-based full-text search over ``DocumentPage.text`` and
    ``DocumentBlock.text``.

    M-12: ``access_scope`` is now optional but, when provided, is
    pushed into the SQL via :func:`apply_access_predicates` so the
    LIMIT-then-filter pattern is gone. The previous flow fetched
    ``limit`` rows from SQL and filtered in memory; restricted users
    with many out-of-scope documents at the top of the result set
    would get empty pages even when a matching document existed
    beyond the cap. The route handler still runs the
    tag/allowed-type post-filter for defense in depth.
    """
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
        # M-12: scope at the SQL layer. ``access_scope`` is a
        # no-op for admins (returns the same SELECT) so this is
        # safe to wire unconditionally from the route handler.
        if access_scope is not None:
            from app.services.tenant_access import apply_access_predicates

            page_stmt = apply_access_predicates(page_stmt, access_scope)
            block_stmt = apply_access_predicates(block_stmt, access_scope)
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
                    source_path=document.source_path,
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
                    source_path=document.source_path,
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]
    finally:
        track_search_latency(time.perf_counter() - start)


# ---------------------------------------------------------------------------
# R1 — HyDE + Multi-query reformulation
# ---------------------------------------------------------------------------


def _hyde_embed(query: str) -> list[float]:
    """Generate a hypothetical answer and embed it instead of the raw query.

    HyDE (Hypothetical Document Embeddings) improves semantic recall
    by embedding a *plausible answer* rather than the user's question.
    The hypothetical answer is generated by a lightweight template
    (no LLM call) so the latency overhead is negligible. On any error
    we fall back to embedding the raw query.
    """
    use_hyde = settings.search_query_transform_strategy in ("hyde", "auto")
    if not use_hyde or not settings.search_use_query_transformer:
        return embed_query_text(query)

    try:
        # Template-based HyDE: no LLM call, just rewrites the query
        # as a statement that would appear in a relevant document.
        hypothetical = (
            f"Segun los documentos disponibles, {query}. "
            f"La informacion encontrada indica que este asunto "
            f"esta relacionado con los datos del sistema."
        )
        return embed_query_text(hypothetical)
    except Exception as exc:  # noqa: BLE001
        # Real failure (network, provider down, embedding model error).
        # Fall back to the raw query so the search still works, but
        # log the cause so operators can see HyDE silently breaking.
        logger.warning("HyDE embed failed (%s); falling back to raw query", exc)
        return embed_query_text(query)


def _multi_query_reformulations(query: str) -> list[str]:
    """Generate alternative phrasings of the query for multi-query retrieval.

    Returns the original query plus 2 reformulations (synonym
    expansion, different phrasing). The caller runs semantic search
    on each and merges the results. No LLM call; uses a simple
    template-based approach.
    """
    reformulations = [query]

    # Reformulation 1: add context words
    reformulations.append(f"informacion sobre {query}")

    # Reformulation 2: rephrase as a statement
    reformulations.append(f"datos relacionados con {query}")

    return reformulations


def _use_multi_query_strategy() -> bool:
    """Whether the current settings say multi-query reformulation
    should run. Gated by the same flag as HyDE so an operator can
    turn both on/off together.
    """
    if not settings.search_use_query_transformer:
        return False
    return settings.search_query_transform_strategy in ("multi_query", "auto")


def _result_key(result: SearchResult) -> tuple[int, int | None, int | None]:
    """Stable identity for a search hit: same (doc, page, block) means
    the same chunk, regardless of score or source label."""
    return (result.document_id, result.page_number, result.block_id)


def _merge_reformulation_results(
    result_lists: list[list[SearchResult]],
    *,
    limit: int,
    k: int = 60,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion across multiple reformulation result lists.

    Each reformulation returns its own ranked list. The fused score
    for an item is ``Σ 1 / (k + rank + 1)`` across lists, with the
    best score (lowest rank) kept on the merged SearchResult. Items
    that appear in multiple lists are boosted; items unique to one
    list keep a non-zero score so they still surface.

    The function is pure (no DB / no cache) so it is easy to test
    in isolation and cheap to call per query.
    """
    scores: dict[tuple[int, int | None, int | None], float] = {}
    items: dict[tuple[int, int | None, int | None], SearchResult] = {}
    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            key = _result_key(result)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            # Keep the first occurrence of the result for the merged
            # payload (excerpt / filename / type) but use the fused
            # score in the output.
            items.setdefault(key, result)
    ranked = sorted(scores, key=scores.get, reverse=True)[:limit]
    out: list[SearchResult] = []
    for key in ranked:
        original = items[key]
        out.append(
            replace(
                original,
                score=round(scores[key], 6),
                source_type="semantic_multi_query",
            )
        )
    return out


def _run_semantic_search(
    db: Session,
    *,
    query_embedding: list[float],
    normalized_query: str,
    limit: int,
    filters: dict | None,
) -> list[SearchResult]:
    """Execute one semantic-search pass for a single query embedding.

    Extracted from :func:`search_semantic` so the multi-query
    reformulation path can call it once per reformulation. The
    behaviour matches the original single-embedding path (Postgres
    pgvector when available, Python cosine similarity otherwise).
    """
    pg = PgvectorStore()
    if _is_postgres(db):
        pg_filters = dict(filters) if filters else {}
        matches = pg.search(db, query_embedding=query_embedding, limit=limit, filters=pg_filters)
        source_paths: dict[int, str | None] = {}
        if matches:
            doc_ids = [m.document_id for m in matches]
            doc_rows = db.execute(
                select(Document.id, Document.source_path).where(Document.id.in_(doc_ids))
            ).all()
            source_paths = {row[0]: row[1] for row in doc_rows}
        return [
            SearchResult(
                document_id=match.document_id,
                original_filename=match.original_filename,
                document_type=match.document_type,
                status=match.status,
                page_number=match.page_number,
                block_id=None,
                score=match.score,
                excerpt=_excerpt(match.excerpt, normalized_query),
                ocr_confidence=None,
                source_type="semantic_chunk",
                source_path=source_paths.get(match.document_id),
            )
            for match in matches
        ]

    # SQLite / other: Python cosine similarity
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
            score = _lexical_overlap_score(normalized_query, chunk.chunk_text)
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
                excerpt=_excerpt(chunk.chunk_text, normalized_query),
                ocr_confidence=None,
                source_type="semantic_chunk",
                source_path=document.source_path,
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)[:limit]


def search_semantic(
    db: Session, query: str, limit: int = 10, filters: dict | None = None
) -> list[SearchResult]:
    start = time.perf_counter()
    try:
        normalized = query.strip()
        if not normalized:
            return []

        cache_key = _make_search_cache_key(normalized, limit, filters, "semantic")
        cached = cache_service.get(cache_key)
        if cached is not None:
            return [_dict_to_search_result(r) for r in cached]

        # R1 — HyDE: embed a hypothetical answer instead of the raw
        # query so the semantic search matches *documents that contain
        # the answer* rather than *documents that mention the query
        # terms*. Falls back to the raw query on any error.
        query_embedding = _hyde_embed(normalized)

        if _use_multi_query_strategy():
            # Multi-query: embed the original + reformulations, run a
            # search per embedding, then merge with RRF. Each per-pass
            # ``limit`` is the same as the final ``limit`` so the fusion
            # has enough candidates. Failures on individual
            # reformulations (e.g. provider outage) degrade gracefully
            # to a single-query search.
            reformulations = _multi_query_reformulations(normalized)
            per_pass_limit = max(limit, 10)
            per_pass: list[list[SearchResult]] = []
            for reformulation in reformulations:
                try:
                    embedding = _hyde_embed(reformulation)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Multi-query embed failed for one reformulation (%s); skipping it",
                        exc,
                    )
                    continue
                per_pass.append(
                    _run_semantic_search(
                        db,
                        query_embedding=embedding,
                        normalized_query=normalized,
                        limit=per_pass_limit,
                        filters=filters,
                    )
                )
            if not per_pass:
                # Every reformulation failed; fall back to the primary
                # single-query search so the user still gets results.
                results_sorted = _run_semantic_search(
                    db,
                    query_embedding=query_embedding,
                    normalized_query=normalized,
                    limit=limit,
                    filters=filters,
                )
            else:
                results_sorted = _merge_reformulation_results(per_pass, limit=limit)
            cache_service.set(
                cache_key,
                [_search_result_to_dict(r) for r in results_sorted],
                SEARCH_CACHE_TTL,
            )
            return results_sorted

        results_sorted = _run_semantic_search(
            db,
            query_embedding=query_embedding,
            normalized_query=normalized,
            limit=limit,
            filters=filters,
        )
        cache_service.set(
            cache_key,
            [_search_result_to_dict(r) for r in results_sorted],
            SEARCH_CACHE_TTL,
        )
        return results_sorted
    finally:
        track_search_latency(time.perf_counter() - start)


def search_hybrid(
    db: Session, query: str, limit: int = 10, filters: dict | None = None
) -> list[SearchResult]:
    start = time.perf_counter()
    try:
        cache_key = _make_search_cache_key(query.strip(), limit, filters, "hybrid")
        cached = cache_service.get(cache_key)
        if cached is not None:
            return [_dict_to_search_result(r) for r in cached]

        from app.services.bm25 import search_bm25
        from app.services.metrics import track_search_strategy_used

        effective_limit = max(limit, 10)

        # Run text, semantic, and BM25 searches in parallel for
        # lower latency. Each strategy is independent and hits a
        # different code path (ILIKE, pgvector, tsvector).
        futures = {}
        text_results: list[SearchResult] = []
        semantic_results: list[SearchResult] = []
        bm25_results: list[SearchResult] = []

        futures[_search_pool.submit(search_text, db, query, effective_limit, filters)] = "text"
        futures[
            _search_pool.submit(search_semantic, db, query, effective_limit, filters)
        ] = "semantic"
        if settings.search_use_bm25:
            futures[
                _search_pool.submit(search_bm25, db, query, effective_limit, filters)
            ] = "bm25"

        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s search failed: %s", name, exc)
                continue
            if name == "text":
                text_results = result
            elif name == "semantic":
                semantic_results = result
            elif name == "bm25":
                bm25_results = result

        track_search_strategy_used("hybrid", "executed")

        # Merge with a larger pool so the reranker has enough
        # candidates to work with. The RRF k constant comes from
        # settings; the per-strategy bias is applied through the
        # rank-only contribution (RRF does not use raw scores).
        rerank_pool_size = max(limit * 3, 15)
        merged = merge_hybrid_results(
            text_results,
            semantic_results,
            bm25_results=bm25_results,
            limit=rerank_pool_size,
            k=settings.search_rrf_k,
        )

        # Apply cross-encoder reranker for better precision
        if len(merged) > limit:
            from app.services.reranker import rerank_sync

            merged = rerank_sync(query.strip(), merged, top_k=limit)

        # E5 — MMR diversity pass. We pull a slightly larger
        # pool (so MMR has actual candidates to swap), apply
        # MMR, then trim back to ``limit``. The cross-encoder
        # rerank above already ordered by relevance, so MMR
        # sees a relevance-sorted input and the diversity
        # re-ordering is bounded.
        if settings.search_use_mmr and len(merged) > limit:
            from app.services.mmr import mmr_rerank

            pool_size = settings.search_mmr_pool_size or max(limit * 3, 15)
            mmr_pool = merged[:pool_size]
            mmr_outcome = mmr_rerank(
                mmr_pool,
                top_k=limit,
                lambda_param=settings.search_mmr_lambda,
            )
            merged = mmr_outcome.results

        cache_service.set(cache_key, [_search_result_to_dict(r) for r in merged], SEARCH_CACHE_TTL)

        return merged
    finally:
        track_search_latency(time.perf_counter() - start)


def merge_hybrid_results(
    text_results: list[SearchResult],
    semantic_results: list[SearchResult],
    *,
    bm25_results: list[SearchResult] | None = None,
    limit: int = 10,
    k: int = 60,
) -> list[SearchResult]:
    """Fuse ranked lists from the available retrieval strategies.

    Each strategy contributes ``1.0 / (k + rank + 1)`` per hit to the
    fused score. The RRF machinery is order-sensitive: a strategy
    that returns the right doc at rank 0 has a strong vote, a
    strategy that returns it at rank 7 has a much weaker one.

    BM25 results are included when ``bm25_results`` is not None.
    Backward compatibility: callers that omit ``bm25_results`` keep
    the legacy 2-source fusion.
    """
    scores: dict[tuple[int, int | None, int | None], float] = {}
    items: dict[tuple[int, int | None, int | None], SearchResult] = {}

    for rank, item in enumerate(text_results or []):
        key = (item.document_id, item.page_number, item.block_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items[key] = item

    for rank, item in enumerate(semantic_results or []):
        key = (item.document_id, item.page_number, item.block_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items.setdefault(key, item)

    if bm25_results:
        for rank, item in enumerate(bm25_results):
            key = (item.document_id, item.page_number, item.block_id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            # Prefer the BM25 result when both branches hit the
            # same chunk because BM25 has the cleaner source_type
            # label for the admin UI.
            items[key] = item

    ranked_keys = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [replace(items[key], score=scores[key], source_type="hybrid_rrf") for key in ranked_keys]


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
    """E3 — delegate to the shared filter module so the new
    filters (date range, quality flags, exclude_statuses) apply
    uniformly. Kept as a thin wrapper for backward compatibility
    with callers that pass a raw ``select`` or already-built
    statement.
    """
    from app.services.search_filters import apply_document_filters

    return apply_document_filters(stmt, filters)


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
