from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.local_client import LocalOpenAICompatibleClient
from app.core.config import settings
from app.models import AIAnswer, AIAnswerSource, AIQuestion, Budget, Document, Order, OrderLine, Plan, User
from app.services.tenant_access import (
    AccessScope,
    filter_document_ids_for_scope,
    filter_documents_for_scope,
    filter_records_by_document_scope,
    filter_search_results_for_scope,
    resolve_user_access_scope,
)
from app.services.redaction import redact_sensitive_text
from app.tools import internal

logger = logging.getLogger("app.ai.agent")


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ContextItem:
    title: str
    summary: str
    document_id: int | None = None
    document_filename: str | None = None
    page_number: int | None = None
    block_id: int | None = None
    relevance_score: float | None = None
    excerpt: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class GroundedResponse:
    answer: str
    confidence: float
    model_name: str


def select_tools_for_question(question: str) -> list[ToolCall]:
    normalized = _normalize(question)
    document_number = _extract_document_number(question)

    if "presupuest" in normalized and "acept" in normalized and ("sin pedido" in normalized or "no tienen pedido" in normalized):
        return [ToolCall("get_accepted_budgets_without_order", {})]
    if "linea" in normalized and "pedido" in normalized:
        return [ToolCall("get_order_by_number", {"order_number": document_number or ""})]
    if "ultimo pedido" in normalized or ("pedido" in normalized and document_number):
        return [ToolCall("get_order_by_number", {"order_number": document_number or ""})]
    if "duplicad" in normalized:
        return [ToolCall("get_duplicate_documents", {})]
    if "baja confianza" in normalized or "error ocr" in normalized or "confianza ocr" in normalized:
        return [ToolCall("get_ocr_review_documents", {})]
    if "entidad" in normalized and "referencia" in normalized:
        value = _extract_reference(question)
        return [ToolCall("search_entities", {"entity_type": "reference", "value": value or question})]
    if ("mide" in normalized or "medida" in normalized or "superficie" in normalized) and (
        room_name := _extract_room_name(normalized)
    ):
        return [ToolCall("search_plan_room_measurements", {"room_name": room_name})]
    if "plano" in normalized or "medida" in normalized or "salon" in normalized or "escala" in normalized:
        return [ToolCall("hybrid_search", {"query": question, "filters": {"document_type": "plano", "limit": 8}})]
    return [ToolCall("hybrid_search", {"query": question, "filters": {"limit": 8}})]


async def answer_question(db: Session, *, user: User, question: str, mode: str | None = None) -> AIAnswer:
    # Check cache first
    from app.services.ai_cache import get_cached_answer, cache_answer
    
    cached = get_cached_answer(question, user.id, mode)
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
    
    # Generate new answer
    question_row = AIQuestion(user_id=user.id, question=question)
    db.add(question_row)
    db.flush()

    access_scope = resolve_user_access_scope(db, user)
    tools = select_tools_for_question(question) if mode != "hybrid" else [ToolCall("hybrid_search", {"query": question, "filters": {"limit": 8}})]
    context_items, warnings = collect_context(db, tools, question, access_scope=access_scope)
    context_items = redact_context_items_for_scope(context_items, access_scope)
    grounded = build_grounded_response(question=question, context_items=context_items, warnings=warnings)

    answer_text = grounded.answer
    model_name = grounded.model_name
    if context_items:
        ai_answer = await _try_local_ai_answer(question, context_items, warnings, fallback=grounded.answer)
        if ai_answer:
            answer_text = ai_answer
            model_name = settings.ai_model or grounded.model_name

    answer_row = AIAnswer(
        question_id=question_row.id,
        answer=answer_text,
        confidence=grounded.confidence,
        model_name=model_name,
    )
    db.add(answer_row)
    db.flush()

    sources_data = []
    for source in _dedupe_sources(context_items):
        answer_row.sources.append(
            AIAnswerSource(
                document_id=source.document_id,
                page_number=source.page_number,
                block_id=source.block_id,
                relevance_score=source.relevance_score,
                excerpt=source.excerpt or source.summary,
            )
        )
        sources_data.append({
            "document_id": source.document_id,
            "page_number": source.page_number,
            "block_id": source.block_id,
            "relevance_score": source.relevance_score,
            "excerpt": source.excerpt or source.summary,
        })

    db.commit()
    db.refresh(answer_row)
    
    # Cache the answer for future queries
    cache_answer(
        question=question,
        user_id=user.id,
        answer={
            "answer": answer_text,
            "confidence": grounded.confidence,
            "model_name": model_name,
            "sources": sources_data,
        },
        mode=mode,
    )
    
    return answer_row


def redact_context_items_for_scope(items: list[ContextItem], access_scope: AccessScope) -> list[ContextItem]:
    if access_scope.can_view_prices:
        return items
    return [
        replace(
            item,
            summary=redact_sensitive_text(item.summary),
            excerpt=redact_sensitive_text(item.excerpt) if item.excerpt is not None else None,
        )
        for item in items
    ]


def collect_context(
    db: Session,
    tools: list[ToolCall],
    question: str,
    *,
    access_scope: AccessScope | None = None,
) -> tuple[list[ContextItem], list[str]]:
    context: list[ContextItem] = []
    warnings: list[str] = []
    for tool in tools:
        if tool.name == "get_accepted_budgets_without_order":
            budgets = internal.get_accepted_budgets_without_order(db)
            if access_scope:
                budgets = filter_records_by_document_scope(db, budgets, access_scope)
            context.extend(_budget_context(db, budget) for budget in budgets)
        elif tool.name == "get_order_by_number":
            order_number = tool.arguments.get("order_number") or _extract_document_number(question)
            if not order_number:
                warnings.append("No se ha detectado un numero de pedido en la pregunta.")
                continue
            order = internal.get_order_by_number(db, order_number)
            if order and access_scope:
                order = filter_records_by_document_scope(db, [order], access_scope)[0] if filter_records_by_document_scope(db, [order], access_scope) else None
            if order:
                context.append(_order_context(db, order, include_lines=True))
        elif tool.name == "hybrid_search":
            query = tool.arguments.get("query") or question
            filters = tool.arguments.get("filters") or {"limit": 8}
            results = internal.hybrid_search(db, query, filters)
            if access_scope:
                results = filter_search_results_for_scope(db, results, access_scope)
            context.extend(
                ContextItem(
                    title=result.original_filename,
                    summary=result.excerpt,
                    document_id=result.document_id,
                    document_filename=result.original_filename,
                    page_number=result.page_number,
                    block_id=result.block_id,
                    relevance_score=result.score,
                    excerpt=result.excerpt,
                    confidence=result.ocr_confidence,
                )
                for result in results
            )
        elif tool.name == "get_duplicate_documents":
            documents = internal.get_duplicate_documents(db)
            if access_scope:
                documents = filter_documents_for_scope(db, documents, access_scope)
            context.extend(_document_context(document, "Documento duplicado") for document in documents)
        elif tool.name == "get_ocr_review_documents":
            documents = internal.get_ocr_review_documents(db)
            if access_scope:
                documents = filter_documents_for_scope(db, documents, access_scope)
            context.extend(_document_context(document, "Documento con error o revision OCR") for document in documents)
        elif tool.name == "search_entities":
            entities = internal.search_entities(
                db,
                entity_type=tool.arguments.get("entity_type") or "reference",
                value=tool.arguments.get("value") or question,
            )
            if access_scope:
                allowed_ids = filter_document_ids_for_scope(db, [entity.document_id for entity in entities], access_scope)
                entities = [entity for entity in entities if entity.document_id in allowed_ids]
            for entity in entities:
                document = db.get(Document, entity.document_id)
                if document:
                    context.append(
                        ContextItem(
                            title=f"{entity.entity_type}: {entity.entity_value}",
                            summary=f"{entity.entity_type}={entity.entity_value}",
                            document_id=document.id,
                            document_filename=document.original_filename,
                            page_number=entity.page_number,
                            block_id=entity.source_block_id,
                            relevance_score=entity.confidence,
                            excerpt=entity.entity_value,
                            confidence=entity.confidence,
                        )
                    )
        elif tool.name == "search_plan_room_measurements":
            room_name = tool.arguments.get("room_name") or _extract_room_name(_normalize(question)) or question
            rows = internal.search_plan_room_measurements(db, room_name)
            if access_scope:
                allowed_ids = filter_document_ids_for_scope(db, [document.id for _, _, document in rows], access_scope)
                rows = [(plan, room, document) for plan, room, document in rows if document.id in allowed_ids]
            for plan, room, document in rows:
                measures = []
                if room.area_m2 is not None:
                    measures.append(f"superficie {room.area_m2} m2")
                if room.width_m is not None:
                    measures.append(f"ancho {room.width_m} m")
                if room.length_m is not None:
                    measures.append(f"largo {room.length_m} m")
                if not measures:
                    measures.append("sin medidas verificables")
                if not plan.has_valid_scale and room.source != "ocr_text":
                    warnings.append(
                        f"El plano {document.original_filename} no tiene escala valida; no se deben convertir pixeles a metros."
                    )
                if room.needs_review:
                    warnings.append(f"La estancia {room.name or room_name} requiere revision manual.")
                context.append(
                    ContextItem(
                        title=f"{room.name or room_name} en {document.original_filename}",
                        summary=(
                            f"{room.name or room_name}: {', '.join(measures)}. "
                            f"Fuente {room.source or '-'}; escala {plan.scale_text or 'no valida'}."
                        ),
                        document_id=document.id,
                        document_filename=document.original_filename,
                        page_number=1,
                        relevance_score=room.confidence,
                        excerpt=f"{room.name or room_name}: {', '.join(measures)}",
                        confidence=room.confidence,
                    )
                )

    if not context and any(tool.name == "hybrid_search" and tool.arguments.get("filters", {}).get("document_type") == "plano" for tool in tools):
        warnings.append("No hay datos de planos suficientes. Si la pregunta requiere convertir medidas, se necesita escala valida o cota fiable.")
    if not context and any(tool.name == "search_plan_room_measurements" for tool in tools):
        warnings.append("No hay habitaciones con medidas verificables para esa consulta.")
    return context[:12], warnings


def build_grounded_response(
    *,
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
) -> GroundedResponse:
    if not context_items:
        warning_text = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- No hay fuentes documentales recuperadas."
        return GroundedResponse(
            answer=(
                "Respuesta:\n"
                "No puedo confirmarlo con la informacion disponible.\n\n"
                "Datos:\n"
                "- Sin datos suficientes en la base documental.\n\n"
                "Fuentes:\n"
                "- Sin fuentes documentales recuperadas.\n\n"
                "Confianza:\n"
                "Baja (0%).\n\n"
                "Advertencias:\n"
                f"{warning_text}"
            ),
            confidence=0.0,
            model_name="backend_grounded_fallback",
        )

    confidence = _average_confidence(context_items)
    data_lines = "\n".join(f"{index}. {item.summary}" for index, item in enumerate(context_items[:8], start=1))
    source_lines = "\n".join(f"- {_format_source(item)}" for item in context_items[:8])
    warning_lines = _warning_lines(context_items, warnings)
    return GroundedResponse(
        answer=(
            "Respuesta:\n"
            f"He encontrado {len(context_items)} resultado(s) documentales relacionados con la pregunta.\n\n"
            "Datos:\n"
            f"{data_lines}\n\n"
            "Fuentes:\n"
            f"{source_lines}\n\n"
            "Confianza:\n"
            f"{_confidence_label(confidence)} ({round(confidence * 100)}%).\n\n"
            "Advertencias:\n"
            f"{warning_lines}"
        ),
        confidence=confidence,
        model_name="backend_grounded_fallback",
    )


async def _try_local_ai_answer(
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
    *,
    fallback: str,
) -> str | None:
    if not settings.ai_base_url or not settings.ai_model:
        return None

    context_text = "\n".join(
        f"[{index}] Fuente={_format_source(item)} | Confianza={item.confidence} | Texto={item.summary}"
        for index, item in enumerate(context_items[:8], start=1)
    )
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un asistente documental interno. Responde solo con el contexto entregado. "
                "No inventes datos. Si falta informacion, di exactamente que no puedes confirmarlo. "
                "No generes SQL. Mantien siempre las secciones: Respuesta, Datos, Fuentes, Confianza, Advertencias."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Pregunta: {question}\n\n"
                f"Contexto documental:\n{context_text}\n\n"
                f"Advertencias del backend:\n{warning_text}\n\n"
                "Genera la respuesta final en espanol usando fuentes concretas."
            ),
        },
    ]
    try:
        client = LocalOpenAICompatibleClient()
        answer = await asyncio.wait_for(client.chat(messages, temperature=0.0), timeout=12)
    except asyncio.TimeoutError:
        logger.warning("AI answer timed out for question: %s", question[:100])
        return None
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("AI client request failed: %s - question: %s", exc, question[:100])
        return None
    except Exception as exc:
        logger.error("Unexpected error in AI answer generation: %s - question: %s", exc, question[:100])
        return None
    if not _has_required_sections(answer):
        return fallback
    return answer


def _budget_context(db: Session, budget: Budget) -> ContextItem:
    document = db.get(Document, budget.document_id)
    amount = f"{budget.total_amount:.2f} {budget.currency or ''}".strip() if budget.total_amount is not None else "importe no detectado"
    status = budget.status or ("aceptado" if budget.accepted_detected else "sin estado")
    return ContextItem(
        title=f"Presupuesto {budget.budget_number or budget.id}",
        summary=f"Presupuesto {budget.budget_number or budget.id} - Cliente {budget.client_name or '-'} - {amount} - Estado {status}",
        document_id=document.id if document else budget.document_id,
        document_filename=document.original_filename if document else None,
        page_number=1,
        relevance_score=budget.confidence,
        confidence=budget.confidence,
    )


def _order_context(db: Session, order: Order, *, include_lines: bool = False) -> ContextItem:
    document = db.get(Document, order.document_id)
    amount = f"{order.total_amount:.2f} {order.currency or ''}".strip() if order.total_amount is not None else "importe no detectado"
    summary = f"Pedido {order.order_number or order.id} - Proveedor {order.supplier_name or '-'} - Cliente {order.client_name or '-'} - {amount}"
    if include_lines:
        lines = list(db.scalars(select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id.asc())).all())
        if lines:
            rendered = "; ".join(
                f"{line.reference or '-'} {line.description or ''} x{line.quantity or '-'} total {line.total_price or '-'}"
                for line in lines[:8]
            )
            summary = f"{summary}. Lineas: {rendered}"
    return ContextItem(
        title=f"Pedido {order.order_number or order.id}",
        summary=summary,
        document_id=document.id if document else order.document_id,
        document_filename=document.original_filename if document else None,
        page_number=1,
        relevance_score=order.confidence,
        confidence=order.confidence,
    )


def _document_context(document: Document, prefix: str) -> ContextItem:
    detail = document.error_message or document.status
    return ContextItem(
        title=document.original_filename,
        summary=f"{prefix}: {document.original_filename} - tipo {document.document_type} - estado {document.status} - {detail or ''}",
        document_id=document.id,
        document_filename=document.original_filename,
        relevance_score=document.confidence,
        confidence=document.confidence,
    )


def _dedupe_sources(items: list[ContextItem]) -> list[ContextItem]:
    seen: set[tuple[int | None, int | None, int | None]] = set()
    sources: list[ContextItem] = []
    for item in items:
        key = (item.document_id, item.page_number, item.block_id)
        if key in seen or item.document_id is None:
            continue
        seen.add(key)
        sources.append(item)
    return sources[:10]


def _format_source(item: ContextItem) -> str:
    filename = item.document_filename or item.title
    page = f", pagina {item.page_number}" if item.page_number else ""
    return f"{filename}{page}"


def _warning_lines(items: list[ContextItem], warnings: list[str]) -> str:
    lines = list(warnings)
    if any(item.confidence is not None and item.confidence < 0.8 for item in items):
        lines.append("Hay resultados con confianza inferior al 80%; conviene revisar la fuente.")
    if not lines:
        lines.append("Sin advertencias adicionales.")
    return "\n".join(f"- {line}" for line in lines)


def _average_confidence(items: list[ContextItem]) -> float:
    values = [item.confidence for item in items if item.confidence is not None]
    if not values:
        values = [item.relevance_score for item in items if item.relevance_score is not None]
    if not values:
        return 0.55
    return max(0.0, min(1.0, sum(values) / len(values)))


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "Alta"
    if value >= 0.5:
        return "Media"
    return "Baja"


def _has_required_sections(answer: str) -> bool:
    normalized = _normalize(answer)
    return all(section in normalized for section in ["respuesta", "datos", "fuentes", "confianza", "advertencias"])


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _extract_document_number(text: str) -> str | None:
    match = re.search(r"\b\d{4}/\d+\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b[A-Za-z]{0,8}\d{2,}[-/]\d+\b", text)
    return match.group(0) if match else None


def _extract_reference(text: str) -> str | None:
    match = re.search(r"\b[A-Za-z]{2,}\d{2,}[A-Za-z0-9-]*\b", text)
    return match.group(0) if match else None


def _extract_room_name(normalized_question: str) -> str | None:
    known_rooms = [
        "salon",
        "cocina",
        "dormitorio",
        "habitacion",
        "bano",
        "banio",
        "aseo",
        "pasillo",
        "comedor",
        "terraza",
        "garaje",
        "recibidor",
    ]
    for room in known_rooms:
        if room in normalized_question:
            return "bano" if room == "banio" else room
    match = re.search(r"(?:mide|medida|superficie)\s+(?:del|de la|de el|el|la)?\s*([a-z0-9 ]{3,30})", normalized_question)
    if match:
        return match.group(1).strip()
    return None
