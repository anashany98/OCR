"""Docu-Intel RAG orchestrator and backward-compatible AI facade."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.ai.local_client import ContextSizeExceededError, LocalOpenAICompatibleClient
from app.ai.model_routing import select_chat_model
from app.ai.structured_answer import decide_structured_answer
from app.ai.structured_output import to_structured_response
from app.core.config import settings
from app.models import AIAnswer, AIAnswerSource, AIQuestion, User
from app.services.ai_cache import cache_answer_async
from app.services.business_redaction import redact_business_payload_for_scope
from app.services.tenant_access import (
    access_scope_cache_key,
    filter_documents_for_scope,
    resolve_user_access_scope,
)
from app.tools import internal

# Public surface re-exports kept for backward compatibility.
from .context import (
    LOW_OCR_CONFIDENCE_THRESHOLD,
    LOW_OCR_MARKER,
    ContextItem,
    GroundedResponse,
    _average_confidence,
    _is_low_ocr_context,
    _warnings_with_low_ocr_notice,
    budget_context,
    build_grounded_response,
    clip_excerpt,
    collect_context,
    confidence_label,
    dedupe_sources,
    document_context,
    format_source,
    order_context,
    redact_context_items_for_scope,
    render_document_details,
    warning_lines,
)
from .prompts import (
    _build_ai_messages,
    _build_user_prompt as _build_user_prompt_unused,  # noqa: F401 (kept for tests)
    _context_line_for_ai,
    build_ai_messages,
    build_context_text,
)
from .tools import (
    ToolCall,
    _classify_aggregation,
    _extract_document_number,
    _extract_filenames,
    _extract_reference,
    _extract_room_name,
    _is_aggregation_question,
    _maybe_apply_relevance_filter,
    _money_filters,
    _normalize,
    select_tools_for_question,
)
from .validation import (
    _detect_language,
    build_memory_block,
    has_required_sections,
    looks_like_followup,
    question_is_spanish,
    response_covers_retrieved_sources,
    response_fabricates_documents,
    response_looks_spanish,
    suggest_followups,
)

logger = logging.getLogger("app.ai.agent")


def _format_gate_blocked_answer(gate_eval, active_context) -> str:
    """Backward-compatible wrapper for the confidence-gate formatter."""
    from .confidence_gates import format_gate_blocked_answer

    return format_gate_blocked_answer(gate_eval, active_context)


# ``DetectorFactory.seed = 0`` is set inside validation.py at
# import time. We re-import the module to make the dependency
# explicit (so a test that imports agent.py also imports the
# validation module, which has the langdetect setup).

# ---------------------------------------------------------------------------
# Backward-compatibility aliases
# ---------------------------------------------------------------------------
#
# The original ``agent.py`` exposed every helper with an underscore
# prefix (e.g. ``_question_is_spanish``). The refactored sub-modules
# use the clean public names (``question_is_spanish``) and the
# underscored names only when the helper is truly internal. Tests
# and callers that import the old names keep working because the
# aliases below point at the new implementations. New code should
# import the clean names.
_question_is_spanish = question_is_spanish
_response_looks_spanish = response_looks_spanish
_response_fabricates_documents = response_fabricates_documents
_has_required_sections = has_required_sections
_suggest_followups = suggest_followups
_looks_like_followup = looks_like_followup
_build_memory_block = build_memory_block
_dedupe_sources = dedupe_sources
_extract_filenames = _extract_filenames
_extract_document_number = _extract_document_number
_extract_reference = _extract_reference
_extract_room_name = _extract_room_name
_normalize = _normalize
_money_filters = _money_filters
_context_text_for_ai = build_context_text


def has_answer_context(context_items: list[ContextItem]) -> bool:
    """True when the chat has real system context to answer from.

    Conversation memory is useful for resolving follow-ups, but it is
    not evidence. Do not let it trigger a free-form LLM answer on its own.
    """
    for item in context_items:
        if item.title == "Memoria de la conversacion":
            continue
        if item.document_id is not None:
            return True
        if item.title.startswith("[Estructurado]"):
            return True
    return False


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


async def answer_question(
    db: Session,
    *,
    user: User,
    question: str,
    mode: str | None = None,
    session_id: str | None = None,
) -> AIAnswer:
    """End-to-end: tool selection, context collection, memory injection,
    grounded fallback, optional LLM call, and
    persistence to AIAnswer + AIAnswerSource rows.

    This is the function the API endpoint (``app.api.routes.ai``)
    calls. Everything else in the agent package is a helper.

    ``session_id`` (CTX-2) is the optional opaque identifier the
    client passes to keep an in-conversation state (current budget,
    current document, last intent, …) between turns. When omitted the
    call is stateless and the behaviour is identical to the previous
    version.
    """
    from .active_context import (
        ActiveContext,
        load_active_context,
    )

    # CTX-3: load the active conversation context and resolve any
    # follow-up references in the question ("este presupuesto" → the
    # active budget). The rewritten question is what the tool
    # selector and the LLM prompt see; the resolution is what the
    # scope guard and the intent router consume. When the request is
    # stateless (no session_id) we still build an empty context so
    # the downstream code path is identical.
    active_context: ActiveContext = (
        load_active_context(db, user, session_id) if session_id else ActiveContext()
    )
    from .reference_resolver import resolve_references

    resolved_question, reference_resolution = resolve_references(question, active_context)

    access_scope = resolve_user_access_scope(db, user)
    scope_key = access_scope_cache_key(access_scope)

    # CTX-3: from this point on, the rest of the orchestrator sees the
    # *resolved* question so the tool selector and the LLM prompt
    # receive the [Contexto: ...] block when the user used a follow-up
    # reference. The original question was already used for the cache
    # key above and is preserved in the AIQuestion row.
    question = resolved_question

    # Generate new answer
    question_row = AIQuestion(user_id=user.id, question=question)
    db.add(question_row)
    db.flush()

    # CTX-5: classify the business intent before any tool is called.
    # The classification is stored in the active context (for the
    # next turn) and also used as a hint in the answer header so the
    # admin UI can show "estoy respondiendo a la pregunta X".
    from .intent_router import classify_intent

    intent_cls = classify_intent(question, active_context)
    # Surface the needs_state warning via the orchestrator's log so
    # operators can audit when the router thought the user was
    # following up on an entity that the context no longer carries.
    if intent_cls.needs_state:
        logger.info(
            "Intent %s needs active context but state is empty; "
            "the assistant will ask for clarification.",
            intent_cls.intent,
        )

    # Always run the smart tool selector so the LLM gets the document's
    # entities and relations when the user mentions a specific file or
    # number. The `mode` is just a hint about which search strategy to
    # prefer when multiple are viable.
    tools = select_tools_for_question(question, active_context=active_context)

    # CTX-6: structured-first path. The intent router may have
    # classified the question as one of the business intents that has
    # a dedicated SQL tool. Prepend those tool calls so they run
    # first; the orchestrator still falls back to the regular RAG
    # path when the structured tool returns ``found=False``.
    from .tools import select_structured_tools

    structured_tools = select_structured_tools(question, active_context=active_context)
    if structured_tools:
        tools = structured_tools + tools

    # CTX-4: apply the budget scope guard. When the active context
    # pins a specific budget (and the user did not ask for a global
    # view) the tool arguments are mutated to keep the retrieval
    # inside the active budget folder.
    from .scope_guard import enforce_budget_scope

    scope_outcome = enforce_budget_scope(question=question, state=active_context, tools=tools)
    tools = scope_outcome.tools
    # The scope guard warnings are folded into the orchestrator-level
    # warnings so they reach both the LLM prompt and the grounded
    # fallback.
    scope_warnings: list[str] = list(scope_outcome.warnings)
    if mode == "semantic":
        # Replace the hybrid_search with a more semantic-friendly call by
        # asking the LLM to think about entities first.
        tools = [t for t in tools if t.name != "hybrid_search"] + [
            ToolCall(
                "hybrid_search", {"query": question, "filters": {"limit": 8, "prefer": "semantic"}}
            )
        ]
    context_items, warnings, resolved_doc_id = collect_context(
        db, tools, question, access_scope=access_scope
    )
    # CTX-4: prepend the scope guard warnings so the fallback mentions
    # the active budget explicitly when nothing was found inside it.
    warnings = scope_warnings + warnings

    # CTX-8: evaluate confidence gates as advisory warnings only.
    # Internal workflow preference: always answer, even below the
    # confidence threshold; the warning reaches both prompt and fallback.
    from .confidence_gates import evaluate_gates_for_turn

    gate_eval, gate_warning = evaluate_gates_for_turn(
        db,
        question=question,
        context_items=context_items,
        resolved_doc_id=resolved_doc_id,
    )
    if gate_warning:
        warnings.append(gate_warning)

    # Inject conversation memory: if the question is a short follow-up
    # (e.g. "y las facturas?", "y del mismo proveedor?"), prepend a memory
    # block summarising the entities mentioned in the previous assistant
    # turn so the LLM has the context to resolve the pronoun.
    memory_block = build_memory_block(db, user, question)
    if memory_block:
        context_items.insert(
            0,
            ContextItem(
                title="Memoria de la conversacion",
                summary=memory_block,
                document_id=None,
                document_filename=None,
                page_number=None,
                relevance_score=1.0,
                excerpt=memory_block,
                confidence=None,
                source_path=None,
            ),
        )

    # ... existing code continues with the resolved_doc_id and the LLM call.
    context_items = redact_context_items_for_scope(context_items, access_scope)

    # FASE 6.1: did-you-mean — when no context found, suggest similar docs.
    if not has_answer_context(context_items):
        from app.ai.did_you_mean import suggest_similar_documents

        suggestions = suggest_similar_documents(db, question)
        if suggestions:
            warnings.append(suggestions)

    grounded = build_grounded_response(
        question=question, context_items=context_items, warnings=warnings
    )

    answer_text = grounded.answer
    model_name = grounded.model_name
    model_route = select_chat_model(question)
    structured_decision = None
    fallback_reason: str | None = None
    # Amount answers with weak evidence must not be delegated to a fluent
    # model.  The gate already considers OCR quality, duplicate/review state
    # and empty text; enforce its verdict instead of treating it as advice.
    if gate_eval.is_blocked:
        answer_text = _format_gate_blocked_answer(gate_eval, active_context)
        model_name = "backend_confidence_gate"
        fallback_reason = "confidence_gate:" + ",".join(
            getattr(gate_eval, "gates_open", []) or ["unsafe_evidence"]
        )
    elif settings.ai_structured_answer_enabled:
        structured_decision = decide_structured_answer(
            question,
            context_items,
            can_view_prices=access_scope.can_view_prices,
        )
    if structured_decision is not None:
        answer_text = structured_decision.answer
        model_name = "backend_structured"
    elif has_answer_context(context_items) and settings.ai_base_url and settings.ai_model:
        llm_fallback_reason: list[str] = []
        ai_answer = await _try_local_ai_answer(
            question,
            context_items,
            warnings,
            fallback=grounded.answer,
            model=model_route.model,
            context_tokens=model_route.context_tokens,
            max_output_tokens=model_route.max_output_tokens,
            fallback_reason_sink=llm_fallback_reason,
        )
        # Only adopt the LLM output if it actually produced something new.
        # `_try_local_ai_answer` returns the same `fallback` string when the
        # LLM is misconfigured, fails validation, or hallucinates a filename.
        # In those cases we keep the grounded fallback's answer AND its
        # honest model_name ("backend_grounded_fallback") instead of crediting
        # the LLM for content it did not produce.
        if ai_answer and ai_answer != grounded.answer:
            answer_text = ai_answer
            model_name = model_route.model or grounded.model_name
        else:
            fallback_reason = llm_fallback_reason[0] if llm_fallback_reason else "llm_fallback"
    elif not has_answer_context(context_items):
        fallback_reason = "no_answer_context"

    structured = to_structured_response(answer_text, context_items=context_items, warnings=warnings)

    # Snapshot the resolved document (entities + relations) for the UI.
    # Use hops=2 so the card on the frontend can show the full neighborhood.
    resolved_json: str | None = None
    if resolved_doc_id is not None:
        details = internal.get_document_full_details(db, resolved_doc_id)
        related = internal.get_related_documents(db, resolved_doc_id, hops=2)
        if details is not None:
            if access_scope is not None:
                related = [
                    r
                    for r in related
                    if filter_documents_for_scope(db, [r["document"]], access_scope)
                ]
            # For the closest related documents, also pull their entities
            # so the frontend can render a richer card. We cap at 4 to keep
            # the JSON payload manageable.
            related_payload = []
            for r in related[:6]:
                doc = r["document"]
                entry = {
                    "document_id": doc.id,
                    "filename": doc.original_filename,
                    "source_path": doc.source_path,
                    "document_type": doc.document_type,
                    "relation": r["relation"],
                    "label": r["label"],
                }
                # Always include entities for the strong relations
                # (presupuesto_to_pedido, pedido_to_factura, etc.) and skip
                # generic folder / supplier matches to keep things focused.
                if r["relation"] in {
                    "presupuesto_to_pedido",
                    "pedido_to_presupuesto",
                    "pedido_to_factura",
                    "factura_to_pedido",
                    "factura_to_presupuesto",
                }:
                    rel_details = internal.get_document_full_details(db, doc.id)
                    if rel_details:
                        entry["entities"] = rel_details.get("entities", {})
                related_payload.append(entry)
            payload = redact_business_payload_for_scope(
                {
                    "document": details,
                    "related": related_payload,
                },
                access_scope,
            )
            try:
                resolved_json = json.dumps(payload, default=str, ensure_ascii=False)
            except Exception as exc:
                logger.warning("Could not serialize resolved_document_json: %s", exc)

    # Confidence is evidence quality, never a proxy for whether a fluent
    # model happened to return text.  This keeps a polished answer from
    # looking more certain than the OCR and retrieved sources justify.
    answer_confidence = grounded.confidence
    if gate_eval.is_blocked:
        answer_confidence = min(answer_confidence, 0.2)

    answer_row = AIAnswer(
        question_id=question_row.id,
        answer=answer_text,
        confidence=answer_confidence,
        model_name=model_name,
        resolved_document_json=resolved_json,
        fallback_reason=fallback_reason,
    )
    db.add(answer_row)
    db.flush()

    sources_data = []
    # CR1: Sanitize source references so stale block_id values
    # cannot FK-abort the transaction.
    from app.services.source_sanitizer import sanitize_sources_batch

    raw_sources = [
        {
            "document_id": source.document_id,
            "page_number": source.page_number,
            "block_id": source.block_id,
            "relevance_score": source.relevance_score,
            "excerpt": source.excerpt or source.summary,
        }
        for source in dedupe_sources(context_items)
    ]
    sanitized_sources = sanitize_sources_batch(db, raw_sources)
    for src in sanitized_sources:
        answer_row.sources.append(
            AIAnswerSource(
                document_id=src.document_id,
                page_number=src.page_number,
                block_id=src.block_id,
                relevance_score=src.relevance_score,
                excerpt=src.excerpt,
            )
        )
        sources_data.append(
            {
                "document_id": src.document_id,
                "page_number": src.page_number,
                "block_id": src.block_id,
                "relevance_score": src.relevance_score,
                "excerpt": src.excerpt,
            }
        )

    db.commit()
    db.refresh(answer_row)

    # Cache the answer for future queries
    await cache_answer_async(
        question=question,
        user_id=user.id,
        answer={
            "answer": answer_text,
            "confidence": answer_confidence,
            "model_name": model_name,
            "fallback_reason": fallback_reason,
            "sources": sources_data,
            "structured": structured.to_dict(),
        },
        mode=mode,
        scope_key=scope_key,
        session_id=session_id,
        model=(
            "backend_confidence_gate:exact"
            if gate_eval.is_blocked
            else "backend_structured:exact"
            if structured_decision is not None
            else model_route.cache_key
        ),
    )

    # CTX-2: persist the active context (current budget, current
    # document, last intent, …) so the next turn in the same session
    # can resolve "este presupuesto" / "este pedido" against the same
    # entity. Best-effort: a failure here must not break the answer.
    from .active_context import persist_context_after_answer

    persist_context_after_answer(
        db,
        user=user,
        session_id=session_id,
        intent=intent_cls.intent,
        resolved_doc_id=resolved_doc_id,
        context_items=context_items,
    )

    return answer_row


# ---------------------------------------------------------------------------
# Streaming and one-shot LLM call
# ---------------------------------------------------------------------------


# _try_local_ai_answer extracted to app.ai.local_answer (FASE 6.1)
# Keep the old private import surface so extension code and tests retain the
# agent-level client injection point after the module split.
async def _try_local_ai_answer(
    question,
    context_items,
    warnings,
    *,
    fallback,
    model=None,
    context_tokens=None,
    max_output_tokens=4000,
    fallback_reason_sink=None,
):
    from app.ai.local_answer import try_local_ai_answer

    return await try_local_ai_answer(
        question,
        context_items,
        warnings,
        fallback=fallback,
        model=model,
        context_tokens=context_tokens,
        max_output_tokens=max_output_tokens,
        client_factory=LocalOpenAICompatibleClient,
        fallback_reason_sink=fallback_reason_sink,
    )


from app.ai.local_answer import _polish_answer_text  # noqa: E402,F401 — used in streaming path


@dataclass
class StreamOutcome:
    """Result of a streaming call. ``text`` is the concatenated LLM
    output; ``ok`` is False when the stream failed or the response
    was rejected by validation. The SSE endpoint uses ``ok=False``
    to swap in the grounded fallback instead of the partial stream.
    """

    text: str
    ok: bool
    reason: str | None = None


async def _stream_local_ai_answer(
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
    *,
    model: str | None = None,
    context_tokens: int | None = None,
    max_output_tokens: int = 4000,
) -> AsyncIterator[str | tuple[str, str] | StreamOutcome]:
    """Stream chunks of the LLM's answer. Yields plain-text deltas, optional
    ``("thinking", chunk)`` tuples (reasoning models), and a final
    :class:`StreamOutcome` (``ok=False`` → SSE endpoint swaps in the
    grounded fallback).

    Resilience retries (all buffered, since on retry nothing has been
    streamed yet): (a) ``ContextSizeExceededError`` → halve the context
    budget and retry once; (b) Qwen3 empty answer with ``/no_think`` →
    retry once with thinking enabled. Both log a clear warning so the
    operator can see the root cause.
    """
    selected_model = model or settings.ai_model
    if not settings.ai_base_url or not selected_model:
        return

    context_text = build_context_text(context_items, max_tokens_override=context_tokens)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."

    # Reuse the system + user prompts that the non-streaming path uses, so
    # behaviour is identical between the two endpoints.
    base_messages = build_ai_messages(question, context_text, warning_text)

    accumulated: list[str] = []
    thinking_accumulated: list[str] = []
    aborted = False
    failure_reason: str | None = None
    client = LocalOpenAICompatibleClient(model=selected_model)
    # MiniMax M3 (FASE 1/4) — record the time-to-first-token for
    # the model queue. The timer is reported through
    # track_chat_stream_event with event="delta"; the model
    # caller can also surface it on the SSE stream.
    from time import perf_counter as _perf_counter

    _t_first_token: float | None = None
    _t_model_queue = _perf_counter()
    try:
        # 4000 tokens (was 2000) so Qwen3 thinking-mode can fit both its
        # reasoning trace and a real answer in the same completion.
        async for piece in client.chat_stream(
            base_messages, temperature=0.0, max_tokens=max_output_tokens
        ):
            if _t_first_token is None:
                _t_first_token = _perf_counter()
                try:
                    from app.services.metrics.rag import track_chat_stream_event

                    track_chat_stream_event(
                        "delta",
                        latency_ms=(_t_first_token - _t_model_queue) * 1000.0,
                    )
                except Exception:  # pragma: no cover - metrics never raise
                    pass
            # Pass through ("thinking", ...) tuples unchanged so the SSE
            # endpoint can emit them as their own event type.
            if isinstance(piece, tuple) and len(piece) == 2 and piece[0] == "thinking":
                thinking_accumulated.append(piece[1])  # type: ignore[arg-type]
                yield piece
                continue
            accumulated.append(piece)  # type: ignore[arg-type]
            yield piece  # type: ignore[misc]
    except ContextSizeExceededError:
        # Prompt too big for the loaded context_length (caller fault — the
        # client avoided the circuit breaker). Shrink the budget and retry
        # ONCE, buffered (nothing was streamed yet).
        halved = max(1000, (context_tokens or settings.ai_max_context_tokens or 6000) // 2)
        logger.warning(
            "Stream exceeded context_length — retry budget=%d: %s", halved, question[:100]
        )
        shrunk = build_ai_messages(
            question, build_context_text(context_items, max_tokens_override=halved), warning_text
        )
        try:
            async for piece in client.chat_stream(
                shrunk, temperature=0.0, max_tokens=max_output_tokens
            ):
                if isinstance(piece, tuple) and len(piece) == 2 and piece[0] == "thinking":
                    continue
                accumulated.append(piece)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Context-shrunk stream retry failed: %s", exc)
    except TimeoutError:
        logger.warning("AI stream timed out for question: %s", question[:100])
        aborted = True
        failure_reason = "llm_timeout"
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("AI stream request failed: %s - question: %s", exc, question[:100])
        aborted = True
        failure_reason = "llm_transport_error"
    except Exception as exc:
        logger.error("Unexpected error in AI stream: %s - question: %s", exc, question[:100])
        aborted = True
        failure_reason = "llm_error"

    full = "".join(accumulated)
    # Qwen3 + LM Studio: with ``/no_think`` it can return EMPTY (0 tokens).
    # Retry ONCE with thinking enabled, buffered (nothing streamed yet);
    # only in the pure-empty case (no text AND no reasoning).
    if not full and not thinking_accumulated and not aborted and "qwen" in selected_model.lower():
        logger.warning("Qwen3 empty with /no_think — retry thinking on: %s", question[:100])
        retry_messages = build_ai_messages(
            question, context_text, warning_text, enable_thinking=True
        )
        retry_parts: list[str] = []
        try:
            async for piece in client.chat_stream(
                retry_messages, temperature=0.0, max_tokens=max_output_tokens
            ):
                if isinstance(piece, tuple) and len(piece) == 2 and piece[0] == "thinking":
                    continue
                retry_parts.append(piece)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qwen3 thinking-enabled retry stream failed: %s", exc)
        full = "".join(retry_parts) or full

    if aborted or not full:
        if not full and thinking_accumulated:
            # Distinguish the "model reasoned but said nothing visible"
            # case from a generic network failure: the user/operator
            # wants to know whether the model is the bottleneck.
            logger.warning(
                "AI stream produced only internal reasoning (%d thinking chunks, "
                "0 visible chunks) for question: %s. Likely cause: Qwen3 "
                "thinking-mode consuming the entire max_tokens budget. "
                "Falling back to grounded response.",
                len(thinking_accumulated),
                question[:100],
            )
        elif not full:
            logger.warning(
                "AI stream produced no visible content for question: %s",
                question[:100],
            )
        yield StreamOutcome(
            text=full,
            ok=False,
            reason=failure_reason or ("llm_only_thinking" if thinking_accumulated else "llm_empty_response"),
        )
        return
    if question_is_spanish(question) and not response_looks_spanish(full):
        logger.warning("Streamed AI response not in Spanish")
        yield StreamOutcome(text=full, ok=False, reason="validation_language")
        return
    if response_fabricates_documents(full, context_items) or not response_covers_retrieved_sources(
        full, context_items, question
    ):
        logger.warning("Streamed AI response failed document/source validation")
        yield StreamOutcome(text=full, ok=False, reason="validation_source_coverage")
        return
    yield StreamOutcome(text=_polish_answer_text(full), ok=True)


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------
#
# This list documents which names the rest of the codebase is
# allowed to import from this module. Anything not listed here is
# an internal implementation detail and should be imported from
# the sub-module (tools, context, prompts, validation) directly.
__all__ = [
    # Dataclasses
    "ContextItem",
    "GroundedResponse",
    "StreamOutcome",
    "ToolCall",
    # Orchestrator
    "answer_question",
    # Tool selection
    "select_tools_for_question",
    # Context building
    "collect_context",
    "redact_context_items_for_scope",
    "build_grounded_response",
    "render_document_details",
    "dedupe_sources",
    "format_source",
    "clip_excerpt",
    "warning_lines",
    "confidence_label",
    "budget_context",
    "order_context",
    "document_context",
    # Prompts
    "build_ai_messages",
    "build_context_text",
    "has_answer_context",
    # Validation
    "response_looks_spanish",
    "question_is_spanish",
    "response_fabricates_documents",
    "has_required_sections",
    "suggest_followups",
    "looks_like_followup",
    "build_memory_block",
    # Internals kept for legacy imports
    "_context_line_for_ai",
    "_build_ai_messages",
    "_question_is_spanish",
    "_response_looks_spanish",
    "_response_fabricates_documents",
    "_has_required_sections",
    "_suggest_followups",
    "_looks_like_followup",
    "_build_memory_block",
    "_dedupe_sources",
    "_is_aggregation_question",
    "_classify_aggregation",
    "_maybe_apply_relevance_filter",
    "_extract_document_number",
    "_extract_reference",
    "_extract_filenames",
    "_extract_room_name",
    "_normalize",
    "_context_text_for_ai",
    "_detect_language",
    "_warnings_with_low_ocr_notice",
    "_is_low_ocr_context",
    "_average_confidence",
    "_money_filters",
    "_try_local_ai_answer",
    # Constants
    "LOW_OCR_CONFIDENCE_THRESHOLD",
    "LOW_OCR_MARKER",
]
