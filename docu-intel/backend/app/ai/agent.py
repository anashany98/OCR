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

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from sqlalchemy.orm import Session

from app.ai.local_client import LocalOpenAICompatibleClient
from app.core.config import settings
from app.models import AIAnswer, AIAnswerSource, AIQuestion, User
from app.services.ai_cache import cache_answer_async, get_cached_answer_async
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
    ContextItem,
    GroundedResponse,
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
from .context import (
    LOW_OCR_CONFIDENCE_THRESHOLD,
    LOW_OCR_MARKER,
    _average_confidence,
    _is_low_ocr_context,
    _warnings_with_low_ocr_notice,
)
from .prompts import (
    _build_ai_messages,
    _build_user_prompt as _build_user_prompt_unused,  # noqa: F401  (kept for tests)
    _context_line_for_ai,
    build_ai_messages,
    build_context_text,
)
from .tools import (
    ToolCall,
    _extract_document_number,
    _extract_filenames,
    _extract_reference,
    _extract_room_name,
    _is_aggregation_question,
    _classify_aggregation,
    _maybe_apply_relevance_filter,
    _normalize,
    _money_filters,
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
    """Render a safe answer when a confidence gate blocks the LLM.

    Used by the orchestrator when a confidence gate is open and the
    question is about an amount. The answer mentions the active
    budget (so the user knows the scope was respected) and lists the
    amount candidates the OCR could see, so the user can verify the
    real number from the document.

    The function delegates the layout to
    :func:`app.ai.answer_format.format_grounded_answer` so the user
    always sees the same five-section layout (directa / evidencia /
    documentos usados / advertencias / que falta) regardless of
    which fallback path produced the response.
    """
    from .answer_format import format_grounded_answer
    from .confidence_gates import GateEvaluation
    from .context import ContextItem

    if not isinstance(gate_eval, GateEvaluation):
        gate_eval = GateEvaluation()
    scope = ""
    if active_context is not None and active_context.current_budget_number:
        scope = f"del presupuesto {active_context.current_budget_number} "
    direct = (
        f"No puedo confirmarlo con seguridad para {scope}porque el documento "
        f"tiene una o varias senales de baja calidad: "
        + ", ".join(gate_eval.gates_open)
        + "."
    )
    # Render the amount candidates as synthetic ContextItems so they
    # show up in the "Evidencia" section of the standard format.
    evidence_items: list[ContextItem] = []
    for cand in gate_eval.amount_candidates[:12]:
        amount = cand.get("amount") or "?"
        document = cand.get("document") or "documento"
        page = cand.get("page")
        conf = cand.get("confidence")
        excerpt = f"importe candidato: {amount}"
        evidence_items.append(
            ContextItem(
                title=f"Cantidad detectada en {document}",
                summary=f"importe candidato: {amount}",
                document_id=None,
                document_filename=document,
                page_number=page,
                relevance_score=0.0,
                excerpt=excerpt,
                confidence=conf,
                source_path=None,
            )
        )
    missing = [
        "No he fabricado un importe a partir de una lectura dudosa.",
        (
            "Si quieres, puedo re-procesar el PDF con OCR avanzado (PaddleOCR v3 / "
            "PP-Structure) para mejorar la lectura. Dime y lo lanzo."
        ),
    ]
    return format_grounded_answer(
        context_items=evidence_items,
        warnings=[direct] + list(gate_eval.gates_open),
        direct=direct,
        missing=missing,
        active_context=active_context,
    )

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
    """End-to-end: cache lookup, tool selection, context collection,
    memory injection, grounded fallback, optional LLM call, and
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
        save_active_context,
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

    resolved_question, reference_resolution = resolve_references(
        question, active_context
    )

    access_scope = resolve_user_access_scope(db, user)
    scope_key = access_scope_cache_key(access_scope)
    cached = await get_cached_answer_async(
        question, user.id, mode, scope_key=scope_key, session_id=session_id
    )
    if cached:
        # Return cached answer as AIAnswer object
        question_row = AIQuestion(user_id=user.id, question=question)
        db.add(question_row)
        db.flush()

        answer_row = AIAnswer(
            question_id=question_row.id,
            answer=cached["answer"],
            confidence=cached["confidence"],
            model_name=cached.get("model_name", "cached"),
        )
        db.add(answer_row)
        db.flush()

        for source in cached.get("sources", []):
            answer_row.sources.append(
                AIAnswerSource(
                    document_id=source.get("document_id"),
                    page_number=source.get("page_number"),
                    block_id=source.get("block_id"),
                    relevance_score=source.get("relevance_score"),
                    excerpt=source.get("excerpt"),
                )
            )

        db.commit()
        db.refresh(answer_row)
        return answer_row

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

    scope_outcome = enforce_budget_scope(
        question=question, state=active_context, tools=tools
    )
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

    # CTX-8: evaluate the confidence gates. When a gate is open and
    # the question expects an amount, the orchestrator will skip the
    # LLM call and produce a safe fallback that lists the amount
    # candidates so the user can verify the answer themselves.
    from .confidence_gates import (
        evaluate_confidence_gates,
        gate_warning_prompt_line,
    )

    resolved_doc_payload_for_gates: dict | None = None
    if resolved_doc_id is not None:
        resolved_doc_payload_for_gates = internal.get_document_full_details(
            db, resolved_doc_id
        )
    gate_eval = evaluate_confidence_gates(
        question=question,
        context_items=context_items,
        resolved_document=resolved_doc_payload_for_gates,
    )
    gate_warning = gate_warning_prompt_line(gate_eval)
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
    # CTX-8: when the gate blocks an amount question, build a safe
    # answer that lists the amount candidates and skip the LLM call
    # so the model cannot override the safety message with a
    # fabricated number. The candidate list also gets attached to
    # the AIAnswer row so the UI can render a verification table.
    amount_candidates_payload: list[dict] = []
    if gate_eval.is_blocked and gate_eval.requires_amount:
        answer_text = _format_gate_blocked_answer(gate_eval, active_context)
        model_name = "backend_grounded_fallback"
        amount_candidates_payload = gate_eval.amount_candidates
    elif context_items:
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
    try:
        from .active_context import update_after_answer

        if session_id:
            ctx: ActiveContext = load_active_context(db, user, session_id)
            resolved_doc_payload: dict | None = None
            if resolved_doc_id is not None:
                details = internal.get_document_full_details(db, resolved_doc_id)
                if details is not None:
                    resolved_doc_payload = details
            update_after_answer(
                ctx,
                intent=intent_cls.intent,
                resolved_document=resolved_doc_payload,
                resolved_budget=(
                    (resolved_doc_payload or {}).get("entities", {}).get("budget")
                    if resolved_doc_payload
                    else None
                ),
                resolved_order=(
                    (resolved_doc_payload or {}).get("entities", {}).get("order")
                    if resolved_doc_payload
                    else None
                ),
                resolved_invoice=(
                    (resolved_doc_payload or {}).get("entities", {}).get("invoice")
                    if resolved_doc_payload
                    else None
                ),
                retrieved_document_ids=[
                    src.document_id for src in dedupe_sources(context_items)
                ],
            )
            save_active_context(db, user, session_id, ctx)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("active_context save failed: %s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

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
    except asyncio.TimeoutError:
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
    return answer


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
    streamed text or fall back to the grounded answer."""
    if not settings.ai_base_url or not settings.ai_model:
        return

    context_text = build_context_text(context_items)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."

    # Reuse the system + user prompts that the non-streaming path uses, so
    # behaviour is identical between the two endpoints.
    base_messages = build_ai_messages(question, context_text, warning_text)

    accumulated: list[str] = []
    aborted = False
    try:
        client = LocalOpenAICompatibleClient()
        async for piece in client.chat_stream(base_messages, temperature=0.0, max_tokens=2000):
            # Pass through ("thinking", ...) tuples unchanged so the SSE
            # endpoint can emit them as their own event type.
            if isinstance(piece, tuple) and len(piece) == 2 and piece[0] == "thinking":
                yield piece
                continue
            accumulated.append(piece)  # type: ignore[arg-type]
            yield piece  # type: ignore[misc]
    except asyncio.TimeoutError:
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
    yield StreamOutcome(text=full, ok=True)


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
