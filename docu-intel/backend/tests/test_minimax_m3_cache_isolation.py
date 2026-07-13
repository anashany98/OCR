"""FASE 7 — cache isolation tests (no skips).

These tests verify the AI cache contract: a hit for one user MUST
NOT serve a different user, a different scope, a different session,
a different model, a different prompt version or a different
knowledge version. They also verify that an explicit
``invalidate_scope`` flushes every entry produced under that scope.

The tests are NOT marked ``skipif`` — they always run. If the
backend is unreachable the suite fails loud, because the contract
is a hard requirement of the FASE 7/8 deliverable.

The tests use the ``cache_service`` directly (Redis is part of the
docker stack) and the ``KnowledgeVersion`` row from the database.
"""
from __future__ import annotations

import time
import uuid

import pytest

from app.services.ai_cache import (
    AI_CACHE_PREFIX,
    CACHE_INDEX_VERSION,
    SEMANTIC_SIM_THRESHOLD,
    _cache_key,
    cache_answer,
    get_cached_answer,
    invalidate_scope,
    invalidate_user_cache,
)
from app.services.cache import cache_service
from app.services.knowledge_version import (
    SINGLE_ROW_ID,
    KnowledgeVersion,
    bump_knowledge_version,
    current_knowledge_version,
)


def _clean_user(user_id: int) -> None:
    """Wipe every cache key tied to ``user_id`` so the test starts
    from a deterministic state."""
    invalidate_user_cache(user_id)
    # Defensive: also remove the semantic index regardless of version
    for k in cache_service.client.scan_iter(
        match=f"ai:sem:{user_id}:*", count=200
    ):
        cache_service.delete(k)


def _put_and_get(
    user_id: int,
    question: str,
    *,
    scope: str = "scope-A",
    session: str = "sess-1",
    mode: str | None = "hybrid",
    model: str = "m1",
    prompt_version: str = "v1",
    knowledge_version: int = 1,
    answer: dict | None = None,
) -> dict | None:
    payload = answer or {"answer": "ok", "confidence": 0.9, "model_name": model}
    cache_answer(
        question,
        user_id,
        payload,
        mode=mode,
        scope_key=scope,
        session_id=session,
        model=model,
        prompt_version=prompt_version,
        knowledge_version=knowledge_version,
    )
    return get_cached_answer(
        question,
        user_id,
        mode=mode,
        scope_key=scope,
        session_id=session,
        model=model,
        prompt_version=prompt_version,
        knowledge_version=knowledge_version,
    )


def test_same_question_different_user_misses():
    _clean_user(9001)
    _clean_user(9002)
    _put_and_get(9001, "que hora es", scope="scopeA")
    hit_other = get_cached_answer(
        "que hora es",
        9002,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    assert hit_other is None


def test_same_question_different_scope_misses():
    _clean_user(9100)
    _put_and_get(9100, "importe total del presupuesto 3987_001", scope="scopeA")
    hit_other = get_cached_answer(
        "importe total del presupuesto 3987_001",
        9100,
        mode="hybrid",
        scope_key="scopeB",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    assert hit_other is None


def test_same_question_different_session_misses():
    _clean_user(9101)
    _put_and_get(9101, "y el otro albaran", scope="scopeA", session="sessA")
    hit_other = get_cached_answer(
        "y el otro albaran",
        9101,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sessB",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    assert hit_other is None


def test_same_question_different_mode_misses():
    _clean_user(9102)
    _put_and_get(9102, "que relacion hay entre los documentos", scope="scopeA", mode="hybrid")
    hit_other = get_cached_answer(
        "que relacion hay entre los documentos",
        9102,
        mode="semantic",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    assert hit_other is None


def test_same_question_different_model_misses():
    _clean_user(9103)
    _put_and_get(9103, "importe del albaran 012770", scope="scopeA", model="modelA")
    hit_other = get_cached_answer(
        "importe del albaran 012770",
        9103,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="modelB",
        prompt_version="v1",
        knowledge_version=1,
    )
    assert hit_other is None


def test_same_question_different_prompt_version_misses():
    _clean_user(9104)
    _put_and_get(
        9104, "ayuda con el documento 3987_001", scope="scopeA", prompt_version="v1"
    )
    hit_other = get_cached_answer(
        "ayuda con el documento 3987_001",
        9104,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v2",
        knowledge_version=1,
    )
    assert hit_other is None


def test_same_question_different_knowledge_version_misses():
    _clean_user(9105)
    _put_and_get(
        9105, "informacion del pdf de incidencia", scope="scopeA", knowledge_version=1
    )
    hit_other = get_cached_answer(
        "informacion del pdf de incidencia",
        9105,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=2,
    )
    assert hit_other is None


def test_revoked_user_does_not_hit_other_user_cache():
    _clean_user(9200)
    _clean_user(9201)
    _put_and_get(9200, "pregunta de prueba", scope="scopeA")
    # Simulate permission revocation by invalidating the original
    # user's cache and confirming the second user is unaffected.
    invalidate_user_cache(9200)
    hit_other = get_cached_answer(
        "pregunta de prueba",
        9201,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    assert hit_other is None
    # The second user can still cache and read their own answer.
    payload = {"answer": "respuesta de 9201", "confidence": 0.7, "model_name": "m1"}
    cache_answer(
        "pregunta de prueba",
        9201,
        payload,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    hit = get_cached_answer(
        "pregunta de prueba",
        9201,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=1,
    )
    # The cache enriches the payload with the isolation vector
    # (prefixed with ``_``). Strip them before comparing.
    visible = {k: v for k, v in (hit or {}).items() if not k.startswith("_")}
    assert visible == payload


def test_invalidate_scope_flushes_only_matching_entries():
    _clean_user(9300)
    _put_and_get(9300, "pregunta scope A", scope="scopeA")
    _put_and_get(9300, "pregunta scope B", scope="scopeB")
    deleted = invalidate_scope("scopeA")
    assert deleted >= 1
    assert (
        get_cached_answer(
            "pregunta scope A",
            9300,
            mode="hybrid",
            scope_key="scopeA",
            session_id="sess-1",
            model="m1",
            prompt_version="v1",
            knowledge_version=1,
        )
        is None
    )
    # The B entry is intact.
    assert (
        get_cached_answer(
            "pregunta scope B",
            9300,
            mode="hybrid",
            scope_key="scopeB",
            session_id="sess-1",
            model="m1",
            prompt_version="v1",
            knowledge_version=1,
        )
        is not None
    )


def test_knowledge_version_bump_is_visible():
    """Bumping the version invalidates the next lookup, even when the
    question text and every other dimension are unchanged."""
    _clean_user(9400)
    _put_and_get(
        9400, "version del conocimiento", scope="scopeA", knowledge_version=1
    )
    # Simulate a write that bumps the version.
    bumped = bump_knowledge_version(None, event="document_updated")  # type: ignore[arg-type]
    assert bumped >= 2
    hit = get_cached_answer(
        "version del conocimiento",
        9400,
        mode="hybrid",
        scope_key="scopeA",
        session_id="sess-1",
        model="m1",
        prompt_version="v1",
        knowledge_version=bumped,
    )
    assert hit is None


def test_cache_key_format_is_stable():
    """Any change in the isolation vector must change the key. The
    test pins the format so a refactor that forgets a dimension
    fails loud."""
    k1 = _cache_key("hola", 1, scope_key="A", session_id="S", model="m", prompt_version="v", knowledge_version=1)
    k2 = _cache_key("hola", 1, scope_key="A", session_id="S", model="m", prompt_version="v", knowledge_version=1)
    assert k1 == k2
    # Change each dimension in turn; the key must change.
    assert k1 != _cache_key("hola", 2, scope_key="A", session_id="S", model="m", prompt_version="v", knowledge_version=1)
    assert k1 != _cache_key("hola", 1, scope_key="B", session_id="S", model="m", prompt_version="v", knowledge_version=1)
    assert k1 != _cache_key("hola", 1, scope_key="A", session_id="T", model="m", prompt_version="v", knowledge_version=1)
    assert k1 != _cache_key("hola", 1, scope_key="A", session_id="S", model="n", prompt_version="v", knowledge_version=1)
    assert k1 != _cache_key("hola", 1, scope_key="A", session_id="S", model="m", prompt_version="w", knowledge_version=1)
    assert k1 != _cache_key("hola", 1, scope_key="A", session_id="S", model="m", prompt_version="v", knowledge_version=2)
    # The key embeds the user_id at the prefix so a Redis scan can
    # isolate every entry produced by a single user.
    assert k1.startswith(f"{AI_CACHE_PREFIX}1:")
