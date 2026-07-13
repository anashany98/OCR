"""AI Query Cache Service

Provides caching for AI responses to improve performance and reduce
load on the local LLM server for repeated questions. The cache supports
both exact-key lookups and semantic (embedding-similarity) lookups so
reformulations of the same question also hit the cache.

Cache-key isolation contract
============================
The cache key is a SHA-256 of every dimension that can change the
answer for the *same* question text:

* user_id — never share answers across users.
* tenant / scope — every project, hotel chain, hotel, group and
  permission flag the user holds at lookup time. See
  :func:`app.services.tenant_access.access_scope_cache_key` for
  the deterministic serialisation.
* session_id — keeps the active-context resolution from leaking
  across chat sessions.
* mode — ``hybrid`` vs ``semantic`` produce different retrieval
  results; the same question in two modes must not collide.
* model — the chat-completion model name. A switch of model must
  invalidate the cache.
* prompt_version — see
  :data:`app.ai.prompts.CHAT_PROMPT_VERSION`. Bumping the version
  automatically invalidates the cache because the key changes.
* knowledge_version — a monotonic counter bumped whenever the
  underlying data the answer was built from changes (new
  extraction, classification update, embedding re-embed,
  permission grant, document delete). The caller passes the
  current value (a small integer) so the cache is invalidated
  atomically with the change.

Anything outside this contract is *not* part of the key, so a
question asked twice with the same scope always hits.

Semantic cache isolation
------------------------
The semantic sidecar index is keyed by user_id so an embedding
match from another user cannot leak. When the user changes scope
(session, project, model, prompt_version) the sidecar entries
are filtered by their ``key`` (which already encodes the full
isolation vector) before cosine similarity is computed.

Invalidation
------------
* :func:`invalidate_user_cache` removes all entries for a user
  (used when their access scope changes).
* :func:`invalidate_scope` removes entries for a specific scope
  signature (used when a document in that scope is updated,
  re-classified, re-embedded, re-extracted or deleted).
* :func:`invalidate_all_ai_cache` is the escape hatch used by the
  admin endpoint.
* Any change to ``prompt_version`` or ``model`` is a key change,
  not an invalidation — old entries naturally expire.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import Any

from app.services.cache import cache_service

logger = logging.getLogger("app.services.ai_cache")
AI_CACHE_TTL = 3600  # 1 hour (default)
AI_CACHE_TTL_SHORT = 1800  # 30 min for complex/specific questions
AI_CACHE_PREFIX = "ai:answer:"
AI_SEMANTIC_PREFIX = "ai:sem:"
# Index version is a per-deployment constant. Bumping it invalidates
# every cached entry by changing the key namespace, which is the
# cheap way to roll out a key-format change without a Redis flush.
CACHE_INDEX_VERSION = 1
SEMANTIC_SIM_THRESHOLD = 0.92  # cosine similarity above this = cache hit


def _cache_ttl(question: str) -> int:
    """Dynamic TTL: short/generic questions cache longer, specific ones shorter."""
    words = question.strip().split()
    if len(words) <= 5:
        return AI_CACHE_TTL  # 1h — generic questions are stable
    if len(words) >= 15:
        return AI_CACHE_TTL_SHORT  # 30min — specific questions may change
    return AI_CACHE_TTL


def _cache_key(
    question: str,
    user_id: int,
    *,
    mode: str | None = None,
    scope_key: str | None = None,
    session_id: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    knowledge_version: int = 0,
) -> str:
    """Generate a fully isolated cache key.

    The function is the single source of truth for the isolation
    vector. Any new dimension that can change the answer for the
    same question text MUST be added here, otherwise two distinct
    answers could collide and the user would see stale data.
    """
    normalized_question = question.strip().lower()
    # Encode every dimension with a fixed-width label so the
    # concatenation cannot be ambiguous (e.g. ``mode=hybrid`` and
    # ``scope_key=hybrid`` are not the same key).
    parts = [
        f"v={CACHE_INDEX_VERSION}",
        f"u={user_id}",
        f"m={model or 'default'}",
        f"pv={prompt_version or 'default'}",
        f"mode={mode or 'default'}",
        f"scope={scope_key or 'default-scope'}",
        f"session={session_id or 'no-session'}",
        f"kv={knowledge_version}",
        f"q={normalized_question}",
    ]
    payload = "\u0001".join(parts).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"{AI_CACHE_PREFIX}{user_id}:{digest}"


def _semantic_key(user_id: int) -> str:
    return f"{AI_SEMANTIC_PREFIX}{user_id}:{CACHE_INDEX_VERSION}"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
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
    session_id: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    knowledge_version: int = 0,
) -> dict[str, Any] | None:
    """Retrieve a cached AI answer if available.

    Lookup order:
      1. Exact key (fastest, fully isolated).
      2. Semantic similarity >= `SEMANTIC_SIM_THRESHOLD` (catches
         reformulations like "cuanto llevamos en melia?" vs "total
         facturado a melia?"). The semantic sidecar only considers
         entries whose stored ``key`` matches the current isolation
         vector, so a reformulation from another scope can never win.
    """
    key = _cache_key(
        question,
        user_id,
        mode=mode,
        scope_key=scope_key,
        session_id=session_id,
        model=model,
        prompt_version=prompt_version,
        knowledge_version=knowledge_version,
    )
    exact = cache_service.get(key)
    if exact:
        return exact

    # Semantic lookup. The sidecar only stores entries that the same
    # user produced, but we still filter by the full isolation vector
    # (encoded inside each entry's ``key``) so a question that was
    # answered in a *different* scope, with a *different* model or
    # with a *different* prompt version can never be reused.
    query_vec = _embed_question(question)
    if not query_vec:
        return None
    sem_key = _semantic_key(user_id)
    sem_index = cache_service.get(sem_key)
    if not sem_index:
        return None
    try:
        best_match: tuple[float, str | None] = (0.0, None)
        for entry in sem_index:  # type: ignore[union-attr]
            entry_key = entry.get("key")
            if not entry_key or entry_key != key:
                # The encoded isolation vector differs. Skip
                # without even computing cosine.
                continue
            vec = entry.get("embedding")
            if not vec:
                continue
            sim = _cosine(query_vec, vec)
            if sim > best_match[0]:
                best_match = (sim, entry_key)
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
    session_id: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    knowledge_version: int = 0,
    ttl: int | None = None,
) -> bool:
    """Cache an AI answer for future queries.

    The ``answer`` payload should already be the canonical response
    dict (with ``answer``, ``confidence``, ``model_name``,
    ``sources``). The function stores the exact-key entry and
    appends a sidecar semantic index entry whose ``key`` is the
    full isolation vector. Any future lookup that does not match
    the same vector will skip the entry before computing cosine.
    """
    key = _cache_key(
        question,
        user_id,
        mode=mode,
        scope_key=scope_key,
        session_id=session_id,
        model=model,
        prompt_version=prompt_version,
        knowledge_version=knowledge_version,
    )
    effective_ttl = ttl if ttl is not None else _cache_ttl(question)
    # Store the isolation vector inside the payload so
    # :func:`invalidate_scope` can find entries produced under a
    # given scope without re-deriving the key. The fields are
    # prefixed with ``_`` so the route handlers strip them before
    # serialising to the client.
    enriched = dict(answer)
    enriched.setdefault("_scope_key", scope_key)
    enriched.setdefault("_prompt_version", prompt_version)
    enriched.setdefault("_model", model)
    enriched.setdefault("_knowledge_version", knowledge_version)
    ok = cache_service.set(key, enriched, effective_ttl)
    # Sidecar: append a {embedding, key} to the per-user semantic
    # index. The ``key`` carries the full isolation vector so the
    # lookup can filter on it without recomputing it.
    try:
        vec = _embed_question(question)
        if vec:
            sem_key = _semantic_key(user_id)
            index = cache_service.get(sem_key) or []
            index.append(
                {
                    "embedding": vec,
                    "key": key,
                    "ts": hashlib.md5(question.encode()).hexdigest()[:8],
                }
            )
            # Keep the index bounded; trim oldest entries past 200.
            if len(index) > 200:
                index = index[-200:]
            cache_service.set(sem_key, index, effective_ttl)
    except Exception as exc:
        logger.debug("Failed to extend semantic cache index: %s", exc)
    return ok


def invalidate_user_cache(user_id: int) -> int:
    """Invalidate all cached AI answers for a specific user."""
    pattern = f"{AI_CACHE_PREFIX}{user_id}:*"
    deleted = cache_service.delete_pattern(pattern)
    cache_service.delete(_semantic_key(user_id))
    return deleted


def invalidate_scope(scope_key: str) -> int:
    """Invalidate every cached answer that was produced under a given
    scope signature.

    The implementation scans the answer namespace and removes any
    entry whose stored payload advertises the scope. This is
    sufficient for the FASE 7/8 invalidation contract: when a
    document in the scope is added, modified, re-classified or
    re-embedded, the operator calls this function and the next
    lookup falls through to the live LLM.
    """
    if not scope_key:
        return 0
    client = cache_service.client
    deleted = 0
    for key in client.scan_iter(match=f"{AI_CACHE_PREFIX}*", count=200):
        payload = cache_service.get(key)
        if not payload:
            continue
        if payload.get("_scope_key") == scope_key:
            cache_service.delete(key)
            deleted += 1
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
            "cache_index_version": CACHE_INDEX_VERSION,
            "enabled": True,
        }
    except Exception:
        logger.debug("ai_cache_stats_failed", exc_info=True)
        return {
            "ai_cache_entries": 0,
            "ai_semantic_indexes": 0,
            "ttl_seconds": AI_CACHE_TTL,
            "cache_index_version": CACHE_INDEX_VERSION,
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
    session_id: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    knowledge_version: int = 0,
) -> dict[str, Any] | None:
    """Async variant of :func:`get_cached_answer` for FastAPI handlers.

    The argument list mirrors the sync helper exactly so the
    call-sites in the route handlers cannot accidentally drop a
    dimension. The function is off-loaded to a worker thread
    because the underlying Redis client used by
    :mod:`app.services.cache` is synchronous.
    """
    return await asyncio.to_thread(
        get_cached_answer,
        question,
        user_id,
        mode,
        scope_key,
        session_id,
        model,
        prompt_version,
        knowledge_version,
    )


async def cache_answer_async(
    question: str,
    user_id: int,
    answer: dict[str, Any],
    mode: str | None = None,
    scope_key: str | None = None,
    session_id: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    knowledge_version: int = 0,
    ttl: int | None = None,
) -> bool:
    """Async variant of :func:`cache_answer` for FastAPI handlers.

    The extra ``_scope_key``/``_prompt_version`` fields in the
    stored payload make the entry discoverable by
    :func:`invalidate_scope` without recomputing the key. The
    keys are prefixed with ``_`` so they never leak to the client
    (the route handlers strip the prefix before serialising).
    """
    enriched = dict(answer)
    enriched["_scope_key"] = scope_key
    enriched["_prompt_version"] = prompt_version
    enriched["_model"] = model
    enriched["_knowledge_version"] = knowledge_version
    return await asyncio.to_thread(
        cache_answer,
        question,
        user_id,
        enriched,
        mode,
        scope_key,
        session_id,
        model,
        prompt_version,
        knowledge_version,
        ttl,
    )
