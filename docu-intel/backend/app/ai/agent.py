"""Docu-Intel RAG agent — orchestrator.

The agent is split across 5 small modules so each concern can be
read in isolation:

============  ======================  ===================================
module        responsibility          lines (approx)
============  ======================  ===================================
``tools``     rule-based tool         select_tools_for_question +
              selection               money/number/filename regex
``context``   context collection,     collect_context + render +
              rendering, redaction,   dedupe + clip + warning lines
              grounding fallback
``prompts``   system + user prompts   build_ai_messages + context line
              + XML/sanitiser wrap    (R2 prompt-injection defence)
``validation`` output validation,     language gate, hallucination
              language detection,     gate, followup suggestions,
              follow-ups, memory      memory block
``agent``     this file               answer_question (sync) +
                                       _stream_local_ai_answer +
                                       _try_local_ai_answer +
                                       resolve_document snapshot
============  ======================  ===================================

Why this split
--------------
The original 1568-line file made it impossible to change one
piece of the pipeline without re-reading the whole thing. A
streaming endpoint change could break the tool selector. A new
R2 sanitiser regex could change the grounded fallback. The five
modules above separate those concerns so a change in one has a
predictable blast radius.

Backward compatibility
----------------------
Older code (and tests) imports public names from this module
directly, e.g. ``from app.ai.agent import select_tools_for_question``.
We re-export the public surface below so the refactor is
invisible to the rest of the codebase.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.ai.local_client import LocalOpenAICompatibleClient
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

# Public surface re-exports (kept for backward compatibility — see
# the module docstring).
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
    _context_line_for_ai,
    build_ai_messages,
    build_context_text,
)
from .prompts import (
    _build_user_prompt as _build_user_prompt_unused,  # noqa: F401  (kept for tests)
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
    response_fabricates_documents,
    response_looks_spanish,
    suggest_followups,
)

logger = logging.getLogger("app.ai.agent")


def _format_gate_blocked_answer(gate_eval, active_context) -> str:
    """Thin wrapper around :func:`app.ai.confidence_gates.format_gate_blocked_answer`.

    Kept here as a private alias so the orchestrator code stays short
    and so a future refactor of the gate helper does not break the
    call site.
    """
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
    tools = select_tools_for_question(question)

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
    grounded = build_grounded_response(
        question=question, context_items=context_items, warnings=warnings
    )

    answer_text = grounded.answer
    model_name = grounded.model_name
    if has_answer_context(context_items) and settings.ai_base_url and settings.ai_model:
        ai_answer = await _try_local_ai_answer(
            question, context_items, warnings, fallback=grounded.answer
        )
        # Only adopt the LLM output if it actually produced something new.
        # `_try_local_ai_answer` returns the same `fallback` string when the
        # LLM is misconfigured, fails validation, or hallucinates a filename.
        # In those cases we keep the grounded fallback's answer AND its
        # honest model_name ("backend_grounded_fallback") instead of crediting
        # the LLM for content it did not produce.
        if ai_answer and ai_answer != grounded.answer:
            answer_text = ai_answer
            model_name = settings.ai_model or grounded.model_name

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

    answer_row = AIAnswer(
        question_id=question_row.id,
        answer=answer_text,
        confidence=grounded.confidence,
        model_name=model_name,
        resolved_document_json=resolved_json,
    )
    db.add(answer_row)
    db.flush()

    sources_data = []
    for source in dedupe_sources(context_items):
        answer_row.sources.append(
            AIAnswerSource(
                document_id=source.document_id,
                page_number=source.page_number,
                block_id=source.block_id,
                relevance_score=source.relevance_score,
                excerpt=source.excerpt or source.summary,
            )
        )
        sources_data.append(
            {
                "document_id": source.document_id,
                "page_number": source.page_number,
                "block_id": source.block_id,
                "relevance_score": source.relevance_score,
                "excerpt": source.excerpt or source.summary,
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
            "confidence": grounded.confidence,
            "model_name": model_name,
            "sources": sources_data,
        },
        mode=mode,
        scope_key=scope_key,
        session_id=session_id,
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


async def _try_local_ai_answer(
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
    *,
    fallback: str,
) -> str | None:
    """One-shot LLM call with the same context as the streaming
    path. Returns the model's answer, or ``fallback`` (and logs
    why) when the LLM is misconfigured, fails validation, or
    fabricates documents.
    """
    if not settings.ai_base_url or not settings.ai_model:
        return None

    context_text = build_context_text(context_items)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."
    messages = build_ai_messages(question, context_text, warning_text)
    try:
        client = LocalOpenAICompatibleClient()
        # The non-stream ``chat()`` already enforces a per-request
        # timeout (``settings.ai_request_timeout_seconds``,
        # default 120s) and ``ai_max_retries`` (default 2)
        # with exponential backoff + jitter inside
        # ``LocalOpenAICompatibleClient._post_chat_completion``.
        # Wrapping it in another ``asyncio.wait_for`` would cap
        # the total wall-clock at 60s and **cut the retry
        # chain short** (audit A6), so the call goes through
        # unchanged and the inner timeout / retry handles the
        # slow / flaky cases instead.
        answer = await client.chat(messages, temperature=0.0)
    except TimeoutError:
        logger.warning("AI answer timed out for question: %s", question[:100])
        return None
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("AI client request failed: %s - question: %s", exc, question[:100])
        return None
    except Exception as exc:
        logger.error(
            "Unexpected error in AI answer generation: %s - question: %s", exc, question[:100]
        )
        return None
    if question_is_spanish(question) and not response_looks_spanish(answer):
        logger.warning("AI response not in Spanish for Spanish question: %s", answer[:200])
        return fallback
    if response_fabricates_documents(answer, context_items):
        logger.warning("AI response mentions documents not in context: %s", answer[:200])
        return fallback
    return _polish_answer_text(answer)


def _polish_answer_text(answer: str) -> str:
    """Minimal cleanup of model output.

    The previous version replaced natural phrases like "segun la fuente 1"
    with "segun la fuente principal", which made the assistant sound
    bureaucratic and stripped the LLM of its own voice. The new system
    prompt tells the model to cite the actual filename inline, so we
    leave phrasing alone and only do a couple of safe mechanical
    cleanups:

    - strip leading/trailing whitespace
    - drop a stray ``[DONE]`` token that some servers append on the
      non-streaming path
    - collapse runs of more than two blank lines
    """
    text = (answer or "").strip()
    if not text:
        return text
    # Defensive cleanup: stray SSE control tokens that should never
    # have leaked into the answer text.
    text = text.replace("[DONE]", "").strip()
    # Collapse 3+ consecutive newlines to 2 (one paragraph break).
    import re

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


@dataclass
class StreamOutcome:
    """Result of a streaming call. ``text`` is the concatenated LLM
    output; ``ok`` is False when the stream failed or the response
    was rejected by validation. The SSE endpoint uses ``ok=False``
    to swap in the grounded fallback instead of the partial stream.
    """

    text: str
    ok: bool


async def _stream_local_ai_answer(
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
) -> AsyncIterator[str | tuple[str, str] | StreamOutcome]:
    """Stream chunks of the LLM's answer as they arrive. Yields
    plain text deltas while the LLM is producing, optional
    ``("thinking", chunk)`` tuples for the model's internal
    reasoning (Qwen3 / reasoning models), and a final
    :class:`StreamOutcome` telling the caller whether to use the
    streamed text or fall back to the grounded answer.

    The previous version returned ``ok=False`` silently when the
    model emitted only ``reasoning_content`` (Qwen3 thinking-mode
    burning the entire ``max_tokens`` budget on internal reasoning
    and never producing a visible answer). That left the user with
    the grounded fallback and no clue why. This version:

    1. Uses a larger ``max_tokens`` ceiling (4000) to leave room for
       a real answer after the thinking trace.
    2. Logs a clear "stream returned only reasoning" warning when
       it happens, so the cause is observable in the backend logs.
    3. Still returns ``ok=False`` so the SSE endpoint can fall back
       to the grounded response - the LLM really did fail to answer
       - but operators can now see the root cause instead of a
       generic "no visible content" warning.
    """
    if not settings.ai_base_url or not settings.ai_model:
        return

    context_text = build_context_text(context_items)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."

    # Reuse the system + user prompts that the non-streaming path uses, so
    # behaviour is identical between the two endpoints.
    base_messages = build_ai_messages(question, context_text, warning_text)

    accumulated: list[str] = []
    thinking_accumulated: list[str] = []
    aborted = False
    try:
        client = LocalOpenAICompatibleClient()
        # 4000 tokens (was 2000) so Qwen3 thinking-mode can fit both its
        # reasoning trace and a real answer in the same completion.
        async for piece in client.chat_stream(
            base_messages, temperature=0.0, max_tokens=4000
        ):
            # Pass through ("thinking", ...) tuples unchanged so the SSE
            # endpoint can emit them as their own event type.
            if isinstance(piece, tuple) and len(piece) == 2 and piece[0] == "thinking":
                thinking_accumulated.append(piece[1])  # type: ignore[arg-type]
                yield piece
                continue
            accumulated.append(piece)  # type: ignore[arg-type]
            yield piece  # type: ignore[misc]
    except TimeoutError:
        logger.warning("AI stream timed out for question: %s", question[:100])
        aborted = True
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("AI stream request failed: %s - question: %s", exc, question[:100])
        aborted = True
    except Exception as exc:
        logger.error("Unexpected error in AI stream: %s - question: %s", exc, question[:100])
        aborted = True

    full = "".join(accumulated)
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
        yield StreamOutcome(text=full, ok=False)
        return
    if question_is_spanish(question) and not response_looks_spanish(full):
        logger.warning("Streamed AI response not in Spanish")
        yield StreamOutcome(text=full, ok=False)
        return
    if response_fabricates_documents(full, context_items):
        logger.warning("Streamed AI response mentions documents not in context")
        yield StreamOutcome(text=full, ok=False)
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
    # Constants
    "LOW_OCR_CONFIDENCE_THRESHOLD",
    "LOW_OCR_MARKER",
]
