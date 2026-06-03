"""Cross-encoder reranker for improving hybrid search precision.

Uses a local reranker model (e.g., bge-reranker-v2-m3) via OpenAI-compatible
/rerank endpoint. Falls back gracefully when unavailable.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.search_service import SearchResult

logger = logging.getLogger("app.services.reranker")

RERANKER_ENDPOINT = "/rerank"
RERANKER_TIMEOUT = 8.0
MIN_CANDIDATES_FOR_RERANK = 5


@dataclass(frozen=True)
class RerankerResult:
    index: int
    score: float


def _reranker_url() -> str | None:
    """Resolve the reranker endpoint URL from settings."""
    base = settings.embedding_base_url.strip() or settings.ai_base_url.strip()
    if not base:
        return None
    clean = base.rstrip("/")
    return f"{clean}{RERANKER_ENDPOINT}"


async def rerank(
    query: str,
    candidates: list[SearchResult],
    top_k: int = 5,
) -> list[SearchResult]:
    """Reorder candidates using a cross-encoder reranker.

    If the reranker endpoint is unavailable or returns an error,
    returns the top_k candidates in their original order as a safe fallback.

    Args:
        query: The search query text.
        candidates: Candidate search results to rerank.
        top_k: Number of top results to return after reranking.

    Returns:
        Reranked list of at most top_k SearchResult items.
    """
    if len(candidates) <= MIN_CANDIDATES_FOR_RERANK:
        return candidates[:top_k]

    url = _reranker_url()
    if url is None:
        return candidates[:top_k]

    documents = [c.excerpt for c in candidates]

    try:
        async with httpx.AsyncClient(timeout=RERANKER_TIMEOUT) as client:
            response = await client.post(
                url,
                json={"query": query, "documents": documents},
            )

        if response.status_code != 200:
            logger.debug("Reranker returned status %d, using original order", response.status_code)
            return candidates[:top_k]

        data = response.json()
        results = data.get("results", [])

        if not results:
            return candidates[:top_k]

        # Build reranked list preserving original SearchResult objects
        reranked: list[SearchResult] = []
        seen: set[int] = set()
        for item in results:
            if isinstance(item, dict):
                idx = item.get("index", -1)
                score = item.get("relevance_score", item.get("score", 0.0))
            elif isinstance(item, (int, float)):
                idx = int(item)
                score = 0.0
            else:
                continue

            if 0 <= idx < len(candidates) and idx not in seen:
                seen.add(idx)
                # Update score with reranker confidence
                original = candidates[idx]
                reranked.append(original.__class__(
                    document_id=original.document_id,
                    original_filename=original.original_filename,
                    document_type=original.document_type,
                    status=original.status,
                    page_number=original.page_number,
                    block_id=original.block_id,
                    score=round(float(score), 6) if score else original.score,
                    excerpt=original.excerpt,
                    ocr_confidence=original.ocr_confidence,
                    source_type=original.source_type,
                ))

        return reranked[:top_k]

    except asyncio.TimeoutError:
        logger.debug("Reranker timed out for query: %s", query[:100])
        return candidates[:top_k]
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.debug("Reranker request failed: %s", exc)
        return candidates[:top_k]
    except Exception as exc:
        logger.warning("Unexpected reranker error: %s", exc)
        return candidates[:top_k]


def rerank_sync(
    query: str,
    candidates: list[SearchResult],
    top_k: int = 5,
) -> list[SearchResult]:
    """Synchronous wrapper for rerank()."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(rerank(query, candidates, top_k))
    # Already in async context — caller should use rerank() directly
    if len(candidates) <= MIN_CANDIDATES_FOR_RERANK:
        return candidates[:top_k]
    return candidates[:top_k]
