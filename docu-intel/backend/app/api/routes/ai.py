from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent import (
    StreamOutcome,
    _build_memory_block,
    _stream_local_ai_answer,
    answer_question,
    build_grounded_response,
    collect_context,
    has_answer_context,
    redact_context_items_for_scope,
    select_tools_for_question,
)
from app.ai.active_context import ActiveContext, load_active_context, persist_context_after_answer
from app.ai.confidence_gates import evaluate_gates_for_turn
from app.ai.local_client import LocalOpenAICompatibleClient  # noqa: F401
from app.ai.reference_resolver import resolve_references
from app.ai.scope_guard import enforce_budget_scope
from app.ai.tools import ToolCall, select_structured_tools
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.database.session import get_db
from app.models import AIAnswer, AIAnswerSource, AIQuestion, User
from app.schemas.ai import AIAnswerRead, AIQuestionRead, AskRequest
from app.services.ai_cache import get_cache_stats, invalidate_all_ai_cache
from app.services.business_redaction import redact_business_payload_for_scope
from app.services.tenant_access import (
    access_scope_cache_key,
    filter_documents_for_scope,
    resolve_user_access_scope,
)

logger = logging.getLogger("app.api.routes.ai")
router = APIRouter()


@router.post("/ask", response_model=AIAnswerRead)
@limiter.limit("10/minute")
async def ask(
    request: Request,
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AIAnswerRead:
    """Non-streaming endpoint. Kept for backward compatibility and for
    quick smoke tests. The UI should prefer `/ask/stream`."""
    answer_row = await answer_question(
        db,
        user=user,
        question=payload.question,
        mode=payload.mode,
        session_id=payload.session_id,
    )
    # Compute follow-ups from the same context the streaming endpoint
    # would have, so the two responses are consistent.
    from app.ai.agent import _suggest_followups  # local import

    tools = select_tools_for_question(payload.question)
    access_scope = resolve_user_access_scope(db, user)
    context_items, _, _ = collect_context(db, tools, payload.question, access_scope=access_scope)
    followups = _suggest_followups(payload.question, None, context_items)
    # Pydantic + from_attributes will copy AIAnswer fields; attach followups
    # by mutating the instance before FastAPI serialises it.
    answer_row.followups = followups  # type: ignore[attr-defined]
    return answer_row


@router.post("/ask/stream")
@limiter.limit("10/minute")
async def ask_stream(
    request: Request,
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the AI answer chunk by chunk as Server-Sent Events.

    Event protocol:
      - event: start  -> { "model": "<name>" }
      - event: delta  -> { "text": "<chunk>" }  (one or many)
      - event: end    -> { "answer": "<full>", "model": "...", "confidence": 0.x,
                           "resolved_document": {...} | null, "sources": [...] }
      - on LLM failure the end event has "fallback": true and the answer is the
        grounded fallback text (so the client can render it directly).
    """
    question = payload.question
    mode = payload.mode
    session_id = payload.session_id

    # 1) build the same context the non-streaming path builds:
    # reference resolution, structured-first tools, active scope and
    # confidence gates. The UI uses this endpoint, so a drift here makes
    # chat ignore data that /ai/ask can already answer from.
    active_context: ActiveContext = (
        load_active_context(db, user, session_id) if session_id else ActiveContext()
    )
    question, _reference_resolution = resolve_references(question, active_context)
    tools = select_tools_for_question(question)
    structured_tools = select_structured_tools(question, active_context=active_context)
    if structured_tools:
        tools = structured_tools + tools
    scope_outcome = enforce_budget_scope(question=question, state=active_context, tools=tools)
    tools = scope_outcome.tools
    if mode == "semantic":
        tools = [t for t in tools if t.name != "hybrid_search"] + [
            ToolCall("hybrid_search", {"query": question, "filters": {"limit": 8, "prefer": "semantic"}})
        ]
    access_scope = resolve_user_access_scope(db, user)
    context_items, warnings, resolved_doc_id = collect_context(
        db, tools, question, access_scope=access_scope
    )
    warnings = list(scope_outcome.warnings) + warnings
    context_items = redact_context_items_for_scope(context_items, access_scope)
    gate_eval, gate_warning = evaluate_gates_for_turn(
        db,
        question=question,
        context_items=context_items,
        resolved_doc_id=resolved_doc_id,
    )
    if gate_warning:
        warnings.append(gate_warning)

    # Inject conversation memory.
    memory_block = _build_memory_block(db, user, question)
    if memory_block:
        from app.ai.agent import ContextItem  # local import to avoid cycle at module load

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

    # 2) build the grounded fallback up front so we always have something
    #    to fall back on.
    grounded = build_grounded_response(
        question=question, context_items=context_items, warnings=warnings
    )
    answer_context_available = has_answer_context(context_items)
    # 3) serialise sources (deduped) for the end event.
    from app.ai.agent import _dedupe_sources  # local import

    sources_payload = []
    for source in _dedupe_sources(context_items):
        sources_payload.append(
            {
                "id": None,
                "document_id": source.document_id,
                "page_number": source.page_number,
                "block_id": source.block_id,
                "relevance_score": source.relevance_score,
                "excerpt": source.excerpt or source.summary,
            }
        )

    # 4) build the resolved-document snapshot for the UI.
    resolved_json: dict | None = None
    if resolved_doc_id is not None:
        from app.tools import internal

        details = internal.get_document_full_details(db, resolved_doc_id)
        related = internal.get_related_documents(db, resolved_doc_id, hops=2)
        if details is not None:
            if access_scope is not None:
                related = [
                    r
                    for r in related
                    if filter_documents_for_scope(db, [r["document"]], access_scope)
                ]
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
            resolved_json = redact_business_payload_for_scope(
                {"document": details, "related": related_payload},
                access_scope,
            )

    async def event_stream() -> AsyncIterator[bytes]:
        # start event: announce the model + that the LLM is running
        start_model = (
            settings.ai_model
            if answer_context_available and settings.ai_base_url and settings.ai_model
            else "backend_grounded_fallback"
        )
        yield (
            b"event: start\ndata: "
            + json.dumps({"model": start_model}).encode()
            + b"\n\n"
        )

        full_text = ""
        model_name = "backend_grounded_fallback"
        confidence = grounded.confidence
        use_fallback = True

        if answer_context_available and settings.ai_base_url and settings.ai_model:
            try:
                async for chunk in _stream_local_ai_answer(question, context_items, warnings):
                    if isinstance(chunk, StreamOutcome):
                        if chunk.ok:
                            full_text = chunk.text
                            model_name = settings.ai_model
                            use_fallback = False
                            yield (
                                b"event: delta\ndata: "
                                + json.dumps({"text": full_text}).encode()
                                + b"\n\n"
                            )
                        break
                    if isinstance(chunk, tuple) and len(chunk) == 2 and chunk[0] == "thinking":
                        continue
            except Exception as exc:
                logger.exception("Streaming failed: %s", exc)

        if use_fallback:
            full_text = grounded.answer
            model_name = grounded.model_name

        # Build the suggested follow-ups (best-effort, fast heuristic).
        from app.ai.agent import _suggest_followups

        followups = _suggest_followups(question, resolved_doc_id, context_items)

        # Persist the final answer to the DB so /ai/history and the work
        # inbox stay in sync with the streamed response.
        question_row = AIQuestion(user_id=user.id, question=question)
        db.add(question_row)
        db.flush()
        answer_row = AIAnswer(
            question_id=question_row.id,
            answer=full_text,
            confidence=confidence,
            model_name=model_name,
            resolved_document_json=json.dumps(resolved_json, default=str, ensure_ascii=False)
            if resolved_json
            else None,
        )
        db.add(answer_row)
        db.flush()
        for src in sources_payload:
            answer_row.sources.append(
                AIAnswerSource(
                    document_id=src["document_id"],
                    page_number=src["page_number"],
                    block_id=src["block_id"],
                    relevance_score=src["relevance_score"],
                    excerpt=src["excerpt"],
                )
            )
        db.commit()
        persist_context_after_answer(
            db,
            user=user,
            session_id=session_id,
            intent=None,
            resolved_doc_id=resolved_doc_id,
            context_items=context_items,
        )

        # Feed the answer into the AI cache so subsequent similar
        # questions (and exact re-asks) skip the LLM. The cache embeds
        # the question and stores it as a sidecar semantic index.
        try:
            from app.services.ai_cache import cache_answer_async as _cache_answer_async

            await _cache_answer_async(
                question=question,
                user_id=user.id,
                answer={
                    "answer": full_text,
                    "confidence": confidence,
                    "model_name": model_name,
                    "sources": sources_payload,
                },
                mode=mode,
                scope_key=access_scope_cache_key(access_scope),
                session_id=session_id,
            )
        except Exception as exc:
            logger.debug("Cache write failed: %s", exc)

        end_payload = {
            "answer": full_text,
            "model": model_name,
            "confidence": confidence,
            "fallback": use_fallback,
            "resolved_document": resolved_json,
            "sources": [
                {
                    "id": s.id,
                    "document_id": s.document_id,
                    "page_number": s.page_number,
                    "block_id": s.block_id,
                    "relevance_score": s.relevance_score,
                    "excerpt": s.excerpt,
                }
                for s in answer_row.sources
            ],
            "followups": followups,
        }
        yield b"event: end\ndata: " + json.dumps(end_payload, ensure_ascii=False).encode() + b"\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/history", response_model=list[AIQuestionRead])
def history(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AIQuestion]:
    return list(
        db.scalars(
            select(AIQuestion)
            .where(AIQuestion.user_id == user.id)
            .order_by(AIQuestion.id.desc())
            .limit(50)
        ).all()
    )


@router.get("/answers/{answer_id}", response_model=AIAnswerRead)
def answer(
    answer_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AIAnswer:
    item = db.get(AIAnswer, answer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Answer not found")
    # Verify the answer belongs to the current user via the question
    question = db.get(AIQuestion, item.question_id)
    if not question or question.user_id != user.id:
        raise HTTPException(status_code=404, detail="Answer not found")
    return item


@router.get("/cache/stats")
def cache_stats(user: User = Depends(get_current_user)) -> dict:
    """Get AI cache statistics. Requires admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view cache stats")
    return get_cache_stats()


@router.delete("/cache")
def clear_cache(user: User = Depends(get_current_user)) -> dict:
    """Clear all AI cache entries. Requires admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can clear the cache")
    deleted = invalidate_all_ai_cache()
    return {"message": "Cache cleared", "entries_deleted": deleted}


# ---------------------------------------------------------------------------
# R3 — feedback loop
# ---------------------------------------------------------------------------


from pydantic import BaseModel, Field  # noqa: E402  (placed near the feedback route)


class FeedbackRequest(BaseModel):
    vote: int = Field(..., ge=-1, le=1, description="+1 for thumbs up, -1 for thumbs down")
    reason: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    accepted: bool
    reason: str
    new_chunk_weight: float | None = None


@router.post(
    "/answers/{answer_id}/feedback",
    response_model=FeedbackResponse,
)
def post_feedback(
    answer_id: int,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FeedbackResponse:
    """R3 — record a 👍/👎 vote on an answer and (when the
    min-votes gate is met) adjust the weights on the cited
    chunks. See :mod:`app.services.feedback_loop` for the
    loop semantics.
    """
    from app.services.feedback_loop import record_feedback

    outcome = record_feedback(
        db,
        answer_id=answer_id,
        user_id=user.id,
        vote=payload.vote,
        reason=payload.reason,
        comment=payload.comment,
    )
    if not outcome.accepted:
        # Map the soft reasons to HTTP status codes so the UI
        # can react (e.g. show "ya has votado esto" vs "respuesta
        # no encontrada").
        status_map = {
            "answer_not_found": 404,
            "invalid_vote": 422,
            "duplicate": 409,
        }
        raise HTTPException(
            status_code=status_map.get(outcome.reason, 400),
            detail=outcome.reason,
        )
    return FeedbackResponse(
        accepted=True,
        reason=outcome.reason,
        new_chunk_weight=outcome.new_chunk_weight,
    )
