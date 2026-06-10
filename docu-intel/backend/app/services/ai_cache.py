"""AI Query Cache Service

Provides caching for AI responses to improve performance and reduce
load on the local LLM server for repeated questions. The cache supports
both exact-key lookups and semantic (embedding-similarity) lookups so
reformulations of the same question also hit the cache.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from typing import Any

from app.core.config import settings
from app.services.cache import cache_service


logger = logging.getLogger("app.services.ai_cache")
AI_CACHE_TTL = 3600  # 1 hour
AI_CACHE_PREFIX = "ai:answer:"
AI_SEMANTIC_PREFIX = "ai:sem:"
SEMANTIC_SIM_THRESHOLD = 0.92  # cosine similarity above this = cache hit


def _cache_key(question: str, user_id: int, mode: str | None = None, scope_key: str | None = None) -> str:
    """Generate a cache key for an AI question.

    Uses SHA256 hash to handle long questions and ensure consistent key length.
    The user_id is placed before the hash so invalidate_user_cache can scan by prefix.
    """
    normalized_question = question.strip().lower()
    content = f"{normalized_question}:{user_id}:{mode or 'default'}:{scope_key or 'default-scope'}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()
    return f"{AI_CACHE_PREFIX}{user_id}:{hash_digest}"


def _semantic_key(user_id: int) -> str:
    return f"{AI_SEMANTIC_PREFIX}{user_id}"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_question(question: str) -> list[float] | None:
    """Return the embedding of `question` using the configured embedding
    model, or None if the service is unavailable."""
    try:
        from app.services.embeddings import embed_text
        return embed_text(question)
    except Exception as exc:
        logger.debug("Embedding service unavailable, skipping semantic cache: %s", exc)
        return None


def get_cached_answer(
    question: str,
    user_id: int,
    mode: str | None = None,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve a cached AI answer if available.

    Lookup order:
      1. Exact key (fastest).
      2. Semantic similarity >= `SEMANTIC_SIM_THRESHOLD` (catches
         reformulations like "cuanto llevamos en melia?" vs "total
         facturado a melia").
    """
    key = _cache_key(question, user_id, mode, scope_key)
    exact = cache_service.get(key)
    if exact:
        return exact

    # Semantic lookup
    query_vec = _embed_question(question)
    if not query_vec:
        return None
    sem_key = _semantic_key(user_id)
    sem_index = cache_service.get(sem_key)
    if not sem_index:
        return None
    try:
        best_match: tuple[float, dict | None] = (0.0, None)
        for entry in sem_index:  # type: ignore[union-attr]
            vec = entry.get("embedding")
            ans_key = entry.get("key")
            if not vec or not ans_key:
                continue
            sim = _cosine(query_vec, vec)
            if sim > best_match[0]:
                best_match = (sim, ans_key)
        if best_match[0] >= SEMANTIC_SIM_THRESHOLD and best_match[1]:
            cached = cache_service.get(best_match[1])
            if cached:
                cached = dict(cached)
                cached["_semantic_match_score"] = round(best_match[0], 3)
                return cached
    except Exception as exc:
        logger.warning("Semantic cache lookup failed: %s", exc)
    return None


def cache_answer(
    question: str,
    user_id: int,
    answer: dict[str, Any],
    mode: str | None = None,
    scope_key: str | None = None,
    ttl: int = AI_CACHE_TTL,
) -> bool:
    """Cache an AI answer for future queries.

    Stores both the exact-key entry and a sidecar semantic index entry
    containing the question's embedding, so subsequent reformulations
    can be served from cache.
    """
    key = _cache_key(question, user_id, mode, scope_key)
    ok = cache_service.set(key, answer, ttl)
    # Sidecar: append a {embedding, key} to the per-user semantic index.
    try:
        vec = _embed_question(question)
        if vec:
            sem_key = _semantic_key(user_id)
            index = cache_service.get(sem_key) or []
            index.append({"embedding": vec, "key": key, "ts": hashlib.md5(question.encode()).hexdigest()[:8]})
            # Keep the index bounded; trim oldest entries past 200.
            if len(index) > 200:
                index = index[-200:]
            cache_service.set(sem_key, index, ttl)
    except Exception as exc:
        logger.debug("Failed to extend semantic cache index: %s", exc)
    return ok


def invalidate_user_cache(user_id: int) -> int:
    """Invalidate all cached AI answers for a specific user."""
    pattern = f"{AI_CACHE_PREFIX}{user_id}:*"
    deleted = cache_service.delete_pattern(pattern)
    cache_service.delete(f"{AI_SEMANTIC_PREFIX}{user_id}")
    return deleted


def invalidate_all_ai_cache() -> int:
    """Invalidate all cached AI answers."""
    deleted = cache_service.delete_pattern(f"{AI_CACHE_PREFIX}*")
    cache_service.delete_pattern(f"{AI_SEMANTIC_PREFIX}*")
    return deleted


def get_cache_stats() -> dict[str, Any]:
    """Get statistics about the AI cache."""
    try:
        client = cache_service.client
        answer_keys = list(client.scan_iter(match=f"{AI_CACHE_PREFIX}*", count=200))
        sem_keys = list(client.scan_iter(match=f"{AI_SEMANTIC_PREFIX}*", count=200))
        return {
            "ai_cache_entries": len(answer_keys),
            "ai_semantic_indexes": len(sem_keys),
            "ttl_seconds": AI_CACHE_TTL,
            "semantic_threshold": SEMANTIC_SIM_THRESHOLD,
            "enabled": True,
        }
    except Exception:
        return {
            "ai_cache_entries": 0,
            "ai_semantic_indexes": 0,
            "ttl_seconds": AI_CACHE_TTL,
            "enabled": False,
            "error": "Unable to connect to cache",
        }
    except Exception:
        return {
            "ai_cache_entries": 0,
            "ttl_seconds": AI_CACHE_TTL,
            "enabled": False,
            "error": "Unable to connect to cache",
        }


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------
# The synchronous helpers above block the event loop while they do
# CPU/IO-bound work (Redis round-trips, embedding calls). FastAPI
# request handlers in ``app.api.routes.ai`` are async, so we expose
# coroutine versions that off-load the work via ``asyncio.to_thread``.
# The public sync API is kept untouched for non-endpoint call-sites
# (Celery tasks, scripts).


async def _embed_question_async(question: str) -> list[float] | None:
    """Async variant of :func:`_embed_question` used by the async cache wrappers.

    The async wrapper for the embedding call delegates to the asyncio-aware
    helper in :mod:`app.services.embeddings` so we never call a blocking
    function from a running event loop.
    """
    try:
        from app.services.embeddings import embed_text_async
        return await embed_text_async(question)
    except Exception as exc:  # pragma: no cover - same semantics as sync version
        logger.debug("Embedding service unavailable, skipping semantic cache: %s", exc)
        return None


async def get_cached_answer_async(
    question: str,
    user_id: int,
    mode: str | None = None,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    """Async variant of :func:`get_cached_answer` for FastAPI handlers.

    Lookup semantics match the sync helper exactly. The function is
    off-loaded to a worker thread because the underlying Redis client
    used by :mod:`app.services.cache` is synchronous.
    """
    return await asyncio.to_thread(
        get_cached_answer,
        question,
        user_id,
        mode,
        scope_key,
    )


async def cache_answer_async(
    question: str,
    user_id: int,
    answer: dict[str, Any],
    mode: str | None = None,
    scope_key: str | None = None,
    ttl: int = AI_CACHE_TTL,
) -> bool:
    """Async variant of :func:`cache_answer` for FastAPI handlers.

    Stores both the exact-key entry and the sidecar semantic index in
    Redis via a worker thread so the event loop stays responsive while
    the answer is being persisted.
    """
    return await asyncio.to_thread(
        cache_answer,
        question,
        user_id,
        answer,
        mode,
        scope_key,
        ttl,
    )
