"""AI Query Cache Service

Provides caching for AI responses to improve performance and reduce
load on the local LLM server for repeated questions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.config import settings
from app.services.cache import cache_service


AI_CACHE_TTL = 3600  # 1 hour
AI_CACHE_PREFIX = "ai:answer:"


def _cache_key(question: str, user_id: int, mode: str | None = None) -> str:
    """Generate a cache key for an AI question.
    
    Uses SHA256 hash to handle long questions and ensure consistent key length.
    """
    normalized_question = question.strip().lower()
    content = f"{normalized_question}:{user_id}:{mode or 'default'}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()
    return f"{AI_CACHE_PREFIX}{hash_digest}"


def get_cached_answer(question: str, user_id: int, mode: str | None = None) -> dict[str, Any] | None:
    """Retrieve a cached AI answer if available.
    
    Args:
        question: The user's question
        user_id: The user's ID for cache scoping
        mode: Optional mode parameter (hybrid, etc.)
    
    Returns:
        Cached answer dict or None if not found
    """
    key = _cache_key(question, user_id, mode)
    return cache_service.get(key)


def cache_answer(
    question: str,
    user_id: int,
    answer: dict[str, Any],
    mode: str | None = None,
    ttl: int = AI_CACHE_TTL,
) -> bool:
    """Cache an AI answer for future queries.
    
    Args:
        question: The user's question
        user_id: The user's ID for cache scoping
        answer: The answer dict to cache
        mode: Optional mode parameter
        ttl: Time-to-live in seconds (default 1 hour)
    
    Returns:
        True if cached successfully, False otherwise
    """
    key = _cache_key(question, user_id, mode)
    return cache_service.set(key, answer, ttl)


def invalidate_user_cache(user_id: int) -> int:
    """Invalidate all cached AI answers for a specific user.
    
    Args:
        user_id: The user's ID
    
    Returns:
        Number of cache entries deleted
    """
    pattern = f"{AI_CACHE_PREFIX}*:{user_id}:*"
    return cache_service.delete_pattern(pattern)


def invalidate_all_ai_cache() -> int:
    """Invalidate all cached AI answers.
    
    Returns:
        Number of cache entries deleted
    """
    return cache_service.delete_pattern(f"{AI_CACHE_PREFIX}*")


def get_cache_stats() -> dict[str, Any]:
    """Get statistics about the AI cache.
    
    Returns:
        Dict with cache statistics
    """
    try:
        client = cache_service.client
        keys = list(client.scan_iter(match=f"{AI_CACHE_PREFIX}*", count=100))
        return {
            "ai_cache_entries": len(keys),
            "ttl_seconds": AI_CACHE_TTL,
            "enabled": True,
        }
    except Exception:
        return {
            "ai_cache_entries": 0,
            "ttl_seconds": AI_CACHE_TTL,
            "enabled": False,
            "error": "Unable to connect to cache",
        }
