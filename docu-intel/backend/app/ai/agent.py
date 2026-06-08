from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.local_client import LocalOpenAICompatibleClient
from app.core.config import settings
from app.models import AIAnswer, AIAnswerSource, AIQuestion, Budget, Document, Order, OrderLine, Plan, User
from app.services.tenant_access import (
    AccessScope,
    access_scope_cache_key,
    filter_document_ids_for_scope,
    filter_documents_for_scope,
    filter_records_by_document_scope,
    filter_search_results_for_scope,
    resolve_user_access_scope,
)
from app.services.redaction import redact_sensitive_text
from app.tools import internal
from app.tools.internal import _money_filters as _money_filters_internal  # re-exported below

logger = logging.getLogger("app.ai.agent")
LOW_OCR_CONFIDENCE_THRESHOLD = 0.70
LOW_OCR_MARKER = "[OCR DUDOSO]"


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
    ocr_confidence: float | None = None
    # Folder-relative path the document was uploaded from. The IA uses it as
    # a disambiguation hint (e.g. two files with the same name in different
    # budget folders).
    source_path: str | None = None


@dataclass(frozen=True)
class GroundedResponse:
    answer: str
    confidence: float
    model_name: str


def select_tools_for_question(question: str) -> list[ToolCall]:
    normalized = _normalize(question)
    document_number = _extract_document_number(question)

    # ---- Aggregation intent (SQL over structured tables) ----
    # Catches the "cuanto nos hemos gastado en X", "cuantos pedidos sin
    # factura" family of questions that cannot be answered with text search.
    if _is_aggregation_question(normalized):
        entity, kind = _classify_aggregation(normalized)
        tools: list[ToolCall] = [ToolCall("aggregate_business", {"entity": entity, "kind": kind})]
        # Also pull the top documents that match, so the LLM can cite them.
        tools.append(ToolCall("hybrid_search", {"query": question, "filters": {"limit": 4}}))
        return tools

    # ---- Specific file mentioned -> lookup + details + relations ----
    # If the user mentions a filename (with extension) we use the lookup path
    # so the LLM gets the document's entities and its connections to the
    # rest of the project, not just text snippets.
    mentioned_filenames = _extract_filenames(question)
    if mentioned_filenames:
        tools = [
            ToolCall("find_document_by_filename", {"query": mentioned_filenames[0]}),
            ToolCall("get_document_full_details", {"document_id": 0}),  # placeholder; replaced after lookup
            ToolCall("get_related_documents", {"document_id": 0}),  # placeholder; replaced after lookup
        ]
        # Always run a hybrid search too in case the user asks for content
        # not covered by the entities (e.g. a specific page or paragraph).
        search_filters: dict = {"limit": 6}
        _maybe_apply_relevance_filter(search_filters, normalized, question)
        tools.append(ToolCall("hybrid_search", {"query": question, "filters": search_filters}))
        return tools

    # ---- Presupuesto / pedido / factura by number -> details + relations ----
    # If the user mentions a number and references a document concept
    # (presupuesto, pedido, factura, etc.), use the same smart chain.
    if document_number and (
        "presupuest" in normalized
        or "pedido" in normalized
        or "factura" in normalized
        or "documento" in normalized
    ):
        # Prefer presupuesto when the user names it explicitly; otherwise
        # fall back to pedido. This avoids searching by pedido number when
        # the user actually asked about the budget.
        if "presupuest" in normalized:
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        elif "pedido" in normalized:
            primary = ToolCall("get_order_by_number", {"order_number": document_number})
        else:
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        return [
            primary,
            ToolCall("get_document_full_details", {"document_id": 0}),
            ToolCall("get_related_documents", {"document_id": 0}),
            ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}}),
        ]

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

    # General question: try hybrid_search with re-ranking filters when the
    # user hints at supplier / client / amount.
    search_filters = {"limit": 8}
    _maybe_apply_relevance_filter(search_filters, normalized, question)
    return [ToolCall("hybrid_search", {"query": question, "filters": search_filters})]


# ---------------------------------------------------------------------------
# Question-classification helpers (aggregation + re-ranking)
# ---------------------------------------------------------------------------

_AGGREGATION_HINTS = (
    "cuanto", "cuanta", "total", "suma", "importe total", "gastado",
    "facturado", "cobrado", "numero de", "cuantos", "cuantas",
    "promedio", "media", "top", "mayor", "menor",
)


def _is_aggregation_question(normalized: str) -> bool:
    return any(h in normalized for h in _AGGREGATION_HINTS)


def _classify_aggregation(normalized: str) -> tuple[str, str]:
    """Return (entity, kind) for an aggregation question.

    - entity: 'budget' | 'order' | 'invoice'
    - kind:   'count' | 'total' | 'top' | 'by_supplier'
    """
    if "factur" in normalized:
        entity = "invoice"
    elif "pedido" in normalized:
        entity = "order"
    else:
        entity = "budget"

    if any(w in normalized for w in ("cuanto", "cuanta", "total", "suma", "importe", "gastado", "facturado")):
        kind = "total"
    elif any(w in normalized for w in ("top", "mayor", "mas alto", "mas grande")):
        kind = "top"
    elif "por proveedor" in normalized or "por cada proveedor" in normalized:
        kind = "by_supplier"
    else:
        kind = "count"
    return entity, kind


def _maybe_apply_relevance_filter(filters: dict, normalized: str, original_question: str) -> None:
    """Add `document_type`, `supplier_ilike`, `client_ilike`, or amount
    bounds to the hybrid_search filters when the user hints at them in the
    question. The search service is responsible for actually applying them
    (see search_service.py)."""
    if "plano" in normalized:
        filters["document_type"] = "plano"
    elif "pedido" in normalized:
        filters["document_type"] = "pedido"
    elif "presupuest" in normalized:
        filters["document_type"] = "presupuesto"
    elif "factura" in normalized:
        filters["document_type"] = "factura"

    money = _money_filters("", original_question)
    if money.get("supplier"):
        filters["supplier_ilike"] = f"%{money['supplier']}%"
    if money.get("client"):
        filters["client_ilike"] = f"%{money['client']}%"
    if money.get("amount_min") is not None:
        filters["amount_min"] = money["amount_min"]
    if money.get("amount_max") is not None:
        filters["amount_max"] = money["amount_max"]


async def answer_question(db: Session, *, user: User, question: str, mode: str | None = None) -> AIAnswer:
    # Check cache first
    from app.services.ai_cache import get_cached_answer, cache_answer

    access_scope = resolve_user_access_scope(db, user)
    scope_key = access_scope_cache_key(access_scope)
    cached = get_cached_answer(question, user.id, mode, scope_key=scope_key)
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

    # Always run the smart tool selector so the LLM gets the document's
    # entities and relations when the user mentions a specific file or
    # number. The `mode` is just a hint about which search strategy to
    # prefer when multiple are viable.
    tools = select_tools_for_question(question)
    if mode == "semantic":
        # Replace the hybrid_search with a more semantic-friendly call by
        # asking the LLM to think about entities first.
        tools = [t for t in tools if t.name != "hybrid_search"] + [
            ToolCall("hybrid_search", {"query": question, "filters": {"limit": 8, "prefer": "semantic"}})
        ]
    context_items, warnings, resolved_doc_id = collect_context(db, tools, question, access_scope=access_scope)

    # Inject conversation memory: if the question is a short follow-up
    # (e.g. "y las facturas?", "y del mismo proveedor?"), prepend a memory
    # block summarising the entities mentioned in the previous assistant
    # turn so the LLM has the context to resolve the pronoun.
    memory_block = _build_memory_block(db, user, question)
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
    grounded = build_grounded_response(question=question, context_items=context_items, warnings=warnings)

    answer_text = grounded.answer
    model_name = grounded.model_name
    if context_items:
        ai_answer = await _try_local_ai_answer(question, context_items, warnings, fallback=grounded.answer)
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
        import json
        details = internal.get_document_full_details(db, resolved_doc_id)
        related = internal.get_related_documents(db, resolved_doc_id, hops=2)
        if details is not None:
            if access_scope is not None:
                related = [
                    r for r in related
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
            payload = {
                "document": details,
                "related": related_payload,
            }
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
        scope_key=scope_key,
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
) -> tuple[list[ContextItem], list[str], int | None]:
    """Returns (context_items, warnings, resolved_document_id).

    `resolved_document_id` is set when the user mentioned a specific file
    and we successfully resolved it; the caller uses it to snapshot
    entities + relations onto the AIAnswer row for the UI."""
    context: list[ContextItem] = []
    warnings: list[str] = []
    # Track the document we resolved from a filename mention, so the
    # follow-up tools (full_details, related_documents) know which id to use.
    resolved_doc_id: int | None = None

    for tool in tools:
        if tool.name == "find_document_by_filename":
            query = tool.arguments.get("query") or ""
            documents = internal.find_document_by_filename(db, query)
            if access_scope:
                documents = filter_documents_for_scope(db, documents, access_scope)
            if documents:
                # If the user asked about a specific file, take the best match.
                resolved = documents[0]
                resolved_doc_id = resolved.id
                context.append(
                    ContextItem(
                        title=f"Documento: {resolved.original_filename}",
                        summary=(
                            f"Tipo: {resolved.document_type} | Estado: {resolved.status} | "
                            f"Confianza: {resolved.confidence} | Paginas: {resolved.page_count} | "
                            f"Ruta: {resolved.source_path}"
                        ),
                        document_id=resolved.id,
                        document_filename=resolved.original_filename,
                        page_number=None,
                        relevance_score=1.0,
                        excerpt=None,
                        confidence=resolved.confidence,
                        source_path=resolved.source_path,
                    )
                )
                if len(documents) > 1:
                    warnings.append(
                        f"He encontrado {len(documents)} documentos cuyo nombre coincide. "
                        f"Estoy explicando el mas reciente ({resolved.original_filename}). "
                        f"Si querias otro, dime el nombre exacto."
                    )
            else:
                warnings.append(f"No he encontrado ningun documento cuyo nombre contenga '{query}'.")
        elif tool.name == "get_document_full_details":
            if resolved_doc_id is None:
                # Skip silently if the lookup didn't resolve a document.
                continue
            details = internal.get_document_full_details(db, resolved_doc_id)
            if details is None:
                continue
            summary = _render_document_details(details)
            # If the vision model described the image, prepend that
            # description to the summary so the LLM uses the actual visual
            # content (not just bad OCR) when explaining the file.
            vision = details.get("vision")
            if vision and vision.get("description"):
                summary = (
                    f"Vision aplicada ({vision.get('model', 'vision')}):\n"
                    f"{vision['description']}\n\n"
                    + summary
                )
            context.append(
                ContextItem(
                    title=f"Entidades extraidas de {details['filename']}",
                    summary=summary,
                    document_id=details["id"],
                    document_filename=details["filename"],
                    page_number=None,
                    relevance_score=0.95,
                    excerpt=summary,
                    confidence=details.get("confidence"),
                    source_path=details.get("source_path"),
                )
            )
        elif tool.name == "get_related_documents":
            if resolved_doc_id is None:
                continue
            related = internal.get_related_documents(db, resolved_doc_id, hops=2)
            if access_scope:
                related = [
                    r for r in related
                    if filter_documents_for_scope(db, [r["document"]], access_scope)
                ]
            for entry in related:
                doc = entry["document"]
                # Multi-hop: for strong relations (depth 1) include the
                # related doc's own entities so the LLM has a full picture.
                detail = internal.get_document_full_details(db, doc.id)
                summary = entry["label"]
                if detail and entry.get("depth", 1) == 1 and detail.get("entities"):
                    summary = entry["label"] + "\n" + _render_document_details(detail)
                context.append(
                    ContextItem(
                        title=doc.original_filename,
                        summary=summary,
                        document_id=doc.id,
                        document_filename=doc.original_filename,
                        page_number=None,
                        relevance_score=0.9,
                        excerpt=entry["label"],
                        confidence=doc.confidence,
                        source_path=doc.source_path,
                    )
                )
        elif tool.name == "get_accepted_budgets_without_order":
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
                if order.document_id:
                    resolved_doc_id = order.document_id
        elif tool.name == "get_budget_by_number":
            budget_number = tool.arguments.get("budget_number") or _extract_document_number(question)
            if not budget_number:
                warnings.append("No se ha detectado un numero de presupuesto en la pregunta.")
                continue
            budget = internal.get_budget_by_number(db, budget_number)
            if budget and access_scope:
                scoped = filter_records_by_document_scope(db, [budget], access_scope)
                budget = scoped[0] if scoped else None
            if budget:
                context.append(_budget_context(db, budget))
                if budget.document_id:
                    resolved_doc_id = budget.document_id
            else:
                warnings.append(
                    f"No he encontrado ningun presupuesto con numero '{budget_number}'. "
                    f"Prueba a buscar por nombre de archivo o por importe/cliente."
                )
        elif tool.name == "aggregate_business":
            entity = tool.arguments.get("entity") or "order"
            kind = tool.arguments.get("kind") or "count"
            result = internal.aggregate_business(db, entity=entity, kind=kind, query=question)
            rows = result.get("rows") or []
            filters = result.get("filters") or {}
            summary_lines = [
                f"Agregado: {result.get('entity')} / {result.get('kind')}",
            ]
            if filters:
                fl = ", ".join(f"{k}={v}" for k, v in filters.items())
                summary_lines.append(f"Filtros aplicados: {fl}")
            summary_lines.append(f"Resultados: {len(rows)}")
            for r in rows:
                label = r.get("label") or r.get("metric")
                val = r.get("value")
                cnt = r.get("count")
                if cnt is not None and val is not None:
                    summary_lines.append(f"- {label}: {val} ({cnt} docs)")
                elif val is not None:
                    summary_lines.append(f"- {label}: {val}")
                else:
                    summary_lines.append(f"- {label}")
            context.append(
                ContextItem(
                    title=f"Agregado {entity}/{kind}",
                    summary="\n".join(summary_lines),
                    document_id=None,
                    document_filename=None,
                    page_number=None,
                    relevance_score=1.0,
                    excerpt="\n".join(summary_lines),
                    confidence=None,
                    source_path=None,
                )
            )
        elif tool.name == "hybrid_search":
            query = tool.arguments.get("query") or question
            filters = tool.arguments.get("filters") or {"limit": 8}
            if access_scope:
                filters = dict(filters)
                filters["_cache_scope"] = access_scope_cache_key(access_scope)
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
                    ocr_confidence=result.ocr_confidence,
                    source_path=result.source_path,
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
                            source_path=document.source_path,
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
                        source_path=document.source_path,
                    )
                )

    if not context and any(tool.name == "hybrid_search" and tool.arguments.get("filters", {}).get("document_type") == "plano" for tool in tools):
        warnings.append("No hay datos de planos suficientes. Si la pregunta requiere convertir medidas, se necesita escala valida o cota fiable.")
    if not context and any(tool.name == "search_plan_room_measurements" for tool in tools):
        warnings.append("No hay habitaciones con medidas verificables para esa consulta.")
    if not context and any(tool.name == "get_related_documents" for tool in tools):
        warnings.append("El documento no tiene vinculos conocidos con otros documentos del proyecto.")
    return context[:14], warnings, resolved_doc_id


def _render_document_details(details: dict) -> str:
    """Render a `get_document_full_details` payload as a short, structured,
    human-readable string that the LLM can use as a grounding fact-sheet."""
    lines: list[str] = []
    entities = details.get("entities") or {}

    if "budget" in entities:
        b = entities["budget"]
        parts = [p for p in [
            f"numero {b.get('number')}" if b.get("number") else None,
            f"cliente {b.get('client')}" if b.get("client") else None,
            f"importe {b.get('total_amount')} {b.get('currency') or ''}".strip() if b.get("total_amount") is not None else None,
            f"fecha {b.get('date')}" if b.get("date") else None,
            f"estado {b.get('status')}" if b.get("status") else None,
            "aceptado" if b.get("accepted") else "no aceptado",
        ] if p]
        if parts:
            lines.append("Presupuesto: " + " | ".join(parts))
        if b.get("line_count"):
            lines.append(f"  lineas: {b['line_count']}")
        for ln in b.get("lines_preview") or []:
            ref = ln.get("reference") or "-"
            desc = (ln.get("description") or "").strip()[:80]
            qty = ln.get("quantity")
            tot = ln.get("total_price")
            lines.append(f"    - {ref} {desc} x{qty if qty is not None else '-'} total {tot if tot is not None else '-'}")

    if "order" in entities:
        o = entities["order"]
        parts = [p for p in [
            f"numero {o.get('number')}" if o.get("number") else None,
            f"proveedor {o.get('supplier')}" if o.get("supplier") else None,
            f"cliente {o.get('client')}" if o.get("client") else None,
            f"importe {o.get('total_amount')} {o.get('currency') or ''}".strip() if o.get("total_amount") is not None else None,
            f"fecha {o.get('date')}" if o.get("date") else None,
        ] if p]
        if parts:
            lines.append("Pedido: " + " | ".join(parts))
        if o.get("related_budget_id"):
            lines.append(f"  derivado del presupuesto id={o['related_budget_id']}")
        if o.get("line_count"):
            lines.append(f"  lineas: {o['line_count']}")

    if "invoice" in entities:
        i = entities["invoice"]
        parts = [p for p in [
            f"numero {i.get('number')}" if i.get("number") else None,
            f"proveedor {i.get('supplier')}" if i.get("supplier") else None,
            f"cliente {i.get('client')}" if i.get("client") else None,
            f"importe {i.get('total_amount')} {i.get('currency') or ''}".strip() if i.get("total_amount") is not None else None,
            f"fecha {i.get('date')}" if i.get("date") else None,
        ] if p]
        if parts:
            lines.append("Factura: " + " | ".join(parts))

    if "plan" in entities:
        pl = entities["plan"]
        parts = [p for p in [
            f"proyecto {pl.get('project_name')}" if pl.get("project_name") else None,
            f"escala {pl.get('scale_text')}" if pl.get("scale_text") else None,
            "escala valida" if pl.get("has_valid_scale") else "escala no valida",
            f"unidad {pl.get('unit')}" if pl.get("unit") else None,
        ] if p]
        if parts:
            lines.append("Plano: " + " | ".join(parts))
        for r in pl.get("rooms_preview") or []:
            lines.append(
                f"    - estancia {r.get('name') or '-'}: "
                f"area {r.get('area_m2')} m2" if r.get("area_m2") is not None else f"    - estancia {r.get('name') or '-'}: sin medidas"
            )

    if "generic" in entities:
        for e in entities["generic"][:6]:
            lines.append(f"Entidad {e.get('type')}: {e.get('value')} (pag. {e.get('page') or '-'})")

    # Markdown-table-derived line items. The parser rendered the page as
    # a markdown table; we extracted structured line items out of it.
    # Showing the first few lines (with their quantities and totals) gives
    # the LLM real numbers instead of forcing it to read raw table cells.
    table_lines = entities.get("table_lines") or []
    if table_lines:
        lines.append(f"Lineas extraidas de la tabla del documento ({len(table_lines)}):")
        for ln in table_lines[:12]:
            ref = ln.get("reference") or "-"
            desc = (ln.get("description") or "").strip()[:60]
            qty = ln.get("quantity")
            unit_price = ln.get("unit_price")
            total = ln.get("total_price")
            parts: list[str] = []
            if qty is not None:
                parts.append(f"x{qty}")
            if unit_price is not None:
                parts.append(f"unit {unit_price}")
            if total is not None:
                parts.append(f"total {total}")
            lines.append(f"  - {ref} {desc} {' '.join(parts)}".rstrip())

    if details.get("error_message"):
        lines.append(f"Aviso: {details['error_message']}")

    if not lines:
        return "No se han extraido entidades estructuradas de este documento."
    return "\n".join(lines)


def build_grounded_response(
    *,
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
) -> GroundedResponse:
    if not context_items:
        warning_text = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- No hay fuentes documentales recuperadas."
        lead = (
            "No he encontrado datos suficientes en los documentos para responder a tu pregunta con seguridad. "
            "Si me das mas contexto (numero de presupuesto, proveedor, ejercicio, etc.) o subes el documento "
            "relevante, lo reviso de nuevo."
        )
        if warnings:
            lead += f"\n\n_Avisos: {warning_text}_"
        return GroundedResponse(
            answer=lead,
            confidence=0.0,
            model_name="backend_grounded_fallback",
        )

    warnings = _warnings_with_low_ocr_notice(context_items, warnings)
    confidence = _average_confidence(context_items)
    top = context_items[0]
    file_label = top.document_filename or top.title or "el documento mas relevante"
    page_label = f" (pagina {top.page_number})" if top.page_number else ""

    raw_text = (top.excerpt or top.summary or "").strip()
    quote = _clip_excerpt(raw_text, 600)
    if quote:
        lead = (
            f"He mirado {len(context_items)} documento(s) que podrian encajar con tu pregunta. "
            f"En **{file_label}**{page_label} aparece esto:\n\n"
            f"> {quote}\n\n"
        )
    else:
        lead = (
            f"He mirado {len(context_items)} documento(s) que podrian encajar, pero el contenido no es "
            f"lo bastante especifico para darte una respuesta detallada. Lo mas relevante que aparece es "
            f"**{file_label}**{page_label}.\n\n"
        )

    # Cite 2-3 additional sources naturally, so the user can jump to them.
    extras: list[str] = []
    for item in context_items[1:4]:
        label = item.document_filename or item.title or "doc"
        if item.page_number:
            label += f" (p. {item.page_number})"
        extras.append(label)
    if extras:
        lead += "Tambien he mirado: " + ", ".join(f"**{x}**" for x in extras) + ".\n\n"

    if warnings:
        lead += "_Avisos: " + "; ".join(warnings) + "_"

    return GroundedResponse(
        answer=lead,
        confidence=confidence,
        model_name="backend_grounded_fallback",
    )

    confidence = _average_confidence(context_items)
    data_lines = "\n".join(f"- {item.summary}" for item in context_items[:8])
    source_lines = "\n".join(f"- {_format_source(item)}" for item in context_items[:8])
    warning_lines = _warning_lines(context_items, warnings)
    top = context_items[0]
    lead = (
        f"He encontrado {len(context_items)} documento(s) relacionado(s) con tu pregunta. "
        f"El mas relevante es {top.document_filename or top.title}"
        + (f", pagina {top.page_number}" if top.page_number else "")
        + "."
    )
    return GroundedResponse(
        answer=(
            "**Respuesta:** "
            f"{lead} "
            "Te resumo lo que dicen las fuentes abajo; si quieres que me centre en un documento concreto, "
            "dime su nombre o numero.\n\n"
            "**Datos:**\n"
            f"{data_lines}\n\n"
            "**Fuentes:**\n"
            f"{source_lines}\n\n"
            "**Confianza:**\n"
            f"{_confidence_label(confidence)} ({round(confidence * 100)}%).\n\n"
            "**Advertencias:**\n"
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

    context_text = _context_text_for_ai(context_items)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."
    messages = _build_ai_messages(question, context_text, warning_text)
    try:
        client = LocalOpenAICompatibleClient()
        # 60s to absorb first-load time of a 26B model in LM Studio. The
        # local server is told the request timeout too (see LocalOpenAICompatibleClient).
        answer = await asyncio.wait_for(client.chat(messages, temperature=0.0), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("AI answer timed out for question: %s", question[:100])
        return None
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("AI client request failed: %s - question: %s", exc, question[:100])
        return None
    except Exception as exc:
        logger.error("Unexpected error in AI answer generation: %s - question: %s", exc, question[:100])
        return None
    if _question_is_spanish(question) and not _response_looks_spanish(answer):
        logger.warning("AI response not in Spanish for Spanish question: %s", answer[:200])
        return fallback
    if _response_fabricates_documents(answer, context_items):
        logger.warning("AI response mentions documents not in context: %s", answer[:200])
        return fallback
    return answer


@dataclass
class StreamOutcome:
    """Result of a streaming call. `text` is the concatenated LLM output;
    `ok` is False when the stream failed or the response was rejected by
    validation. The SSE endpoint uses `ok=False` to swap in the grounded
    fallback instead of the partial stream."""
    text: str
    ok: bool


async def _stream_local_ai_answer(
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
) -> AsyncIterator[str | tuple[str, str] | StreamOutcome]:
    """Stream chunks of the LLM's answer as they arrive. Yields plain text
    deltas while the LLM is producing, optional ("thinking", chunk)
    tuples for the model's internal reasoning (Qwen3 / reasoning models),
    and a final StreamOutcome telling the caller whether to use the
    streamed text or fall back to the grounded answer."""
    if not settings.ai_base_url or not settings.ai_model:
        return

    context_text = _context_text_for_ai(context_items)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."

    # Reuse the system + user prompts that the non-streaming path uses, so
    # behaviour is identical between the two endpoints.
    base_messages = _build_ai_messages(question, context_text, warning_text)

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
    if _question_is_spanish(question) and not _response_looks_spanish(full):
        logger.warning("Streamed AI response not in Spanish")
        yield StreamOutcome(text=full, ok=False)
        return
    if _response_fabricates_documents(full, context_items):
        logger.warning("Streamed AI response mentions documents not in context")
        yield StreamOutcome(text=full, ok=False)
        return
    yield StreamOutcome(text=full, ok=True)


def _context_text_for_ai(context_items: list[ContextItem]) -> str:
    return "\n".join(
        _context_line_for_ai(index, item)
        for index, item in enumerate(context_items[:8], start=1)
    )


def _context_line_for_ai(index: int, item: ContextItem) -> str:
    marker = f" {LOW_OCR_MARKER}" if _is_low_ocr_context(item) else ""
    ocr_confidence = item.ocr_confidence if item.ocr_confidence is not None else "-"
    return (
        f"[{index}]{marker} Fuente={_format_source(item)} | Ruta={item.source_path or '-'} | "
        f"Confianza={item.confidence} | ConfianzaOCR={ocr_confidence} | Texto={item.summary}"
    )


def _build_ai_messages(question: str, context_text: str, warning_text: str) -> list[dict]:
    """Build the system + user messages for the LLM. Used by both the
    streaming and the non-streaming paths so the behaviour stays consistent."""
    return [
        {
            "role": "system",
            "content": (
                "Eres el asistente documental de Docu-Intel, un puesto de trabajo interno para que el equipo "
                "consulte presupuestos, pedidos, facturas y planos. Tu unica fuente de verdad es el bloque "
                "'Contexto documental' que recibes en el mensaje del usuario: lo que NO esta ahi, no existe.\n\n"
                "DENTRO DEL CONTEXTO RECIBIRAS TRES TIPOS DE INFORMACION ESTRUCTURADA:\n"
                "1. **Documento resuelto** (cuando el usuario nombra un archivo): tipo, estado, ruta, "
                "confianza OCR, paginas.\n"
                "2. **Entidades extraidas**: presupuesto (numero, cliente, importe, lineas), pedido "
                "(numero, proveedor, cliente, lineas), factura (numero, importe), plano (proyecto, escala, "
                "estancias con medidas), u otras entidades genericas.\n"
                "3. **Documentos relacionados**: lista de archivos vinculados al principal, con la razon de "
                "la relacion (ej. 'Pedido 60105 derivado de este presupuesto', 'Otro pedido del mismo "
                "proveedor Garcia', 'Factura que paga el pedido 1234').\n"
                "Ademas de eso, recibes extractos literales (texto recuperado) cuando es relevante.\n\n"
                "COMO TRABAJAS CON ESTO:\n"
                "- Cuando el usuario pregunta por un archivo concreto, primero IDENTIFICA QUE ES (tipo "
                "documental, numero, cliente, importe, etc.) usando las entidades extraidas. No te limites "
                "a repetir el nombre del archivo.\n"
                "- CONECTA el archivo con su entorno: si es un presupuesto, explica que pedido genero y si "
                "ese pedido tiene factura. Si es un pedido, menciona de que presupuesto sale y si esta "
                "facturado. Si es un plano, indica el proyecto y las estancias con medidas. Si es un email "
                "(.msg), explica quienes participan, que se pide y cual es el contexto.\n"
                "- Si hay DATOS ESTRUCTURADOS (entidades) y EXTRACTOS, integra los dos: las entidades dan "
                "los hechos clave (numero, importe, fecha), los extractos dan el detalle y el matiz.\n"
                "- Si una entidad existe (ej. importe del presupuesto), usala en vez de 'aproximadamente'.\n\n"
                "- Si una fuente esta marcada como [OCR DUDOSO], advierte que el dato procede de OCR de "
                "baja confianza y que conviene contrastarlo en el documento original.\n\n"
                "COMO HABLAS:\n"
                "- Siempre en espanol, con un tono cercano y profesional, como un companero de trabajo que "
                "conoce el proyecto.\n"
                "- Respondes en prosa natural, como en una conversacion de chat. NO uses secciones rigidas "
                "tipo **Respuesta:**, **Datos:**, **Fuentes:**. NO rellenes formularios.\n"
                "- Si hay varios datos, integrarlos en el discurso en vez de hacer un listado exhaustivo. "
                "Puedes usar una lista breve con - si ayuda a la claridad.\n"
                "- Citas las fuentes de forma natural dentro del texto cuando aportas un dato concreto, por "
                "ejemplo: 'segun el presupuesto JESSICA/252984/1223_001.pdf (pagina 1)' o 'en el pedido del "
                "proveedor Garcia'. No hace falta un apartado final de 'Fuentes'.\n"
                "- Si no encuentras lo que el usuario pide, se honesto: 'No he encontrado datos sobre eso "
                "en los documentos que tengo a la vista. Si me das mas contexto (numero, proveedor, fecha) "
                "lo reviso de nuevo.'\n\n"
                "REGLAS INNEGOCIABLES:\n"
                "1. NUNCA respondas en ingles ni en otro idioma.\n"
                "2. NUNCA inventes datos. Si el contexto no contiene la respuesta, dilo.\n"
                "3. NUNCA menciones nombres de archivo, numeros de pagina, importes, clientes o proveedores "
                "que NO aparezcan literalmente en el contexto.\n"
                "4. NUNCA uses tu conocimiento previo. Solo lo que esta en el contexto."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Pregunta del usuario: {question}\n\n"
                f"Contexto documental disponible (esta es tu UNICA fuente de verdad):\n{context_text}\n\n"
                f"Avisos del sistema: {warning_text}\n\n"
                "Responde en espanol, en prosa natural, citando las fuentes dentro del texto. "
                "Si un dato no esta literalmente en el contexto, NO lo menciones."
            ),
        },
    ]


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
        source_path=document.source_path if document else None,
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
        source_path=document.source_path if document else None,
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
        source_path=document.source_path,
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


def _clip_excerpt(text: str, max_chars: int) -> str:
    """Trim the excerpt at a sentence boundary if possible, appending an ellipsis."""
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    # Try to cut at the last sentence terminator inside the window.
    for terminator in (". ", "; ", ": "):
        idx = clipped.rfind(terminator)
        if idx > max_chars * 0.6:
            return clipped[: idx + 1].rstrip() + "…"
    return clipped.rstrip() + "…"


def _warning_lines(items: list[ContextItem], warnings: list[str]) -> str:
    lines = _warnings_with_low_ocr_notice(items, warnings)
    if any(item.confidence is not None and item.confidence < 0.8 for item in items):
        lines.append("Hay resultados con confianza inferior al 80%; conviene revisar la fuente.")
    if not lines:
        lines.append("Sin advertencias adicionales.")
    return "\n".join(f"- {line}" for line in lines)


def _warnings_with_low_ocr_notice(
    items: list[ContextItem],
    warnings: list[str],
) -> list[str]:
    lines = list(warnings)
    if any(_is_low_ocr_context(item) for item in items):
        notice = (
            "Hay fuentes marcadas como OCR dudoso; conviene contrastar esos datos "
            "con el documento original."
        )
        if notice not in lines:
            lines.append(notice)
    return lines


def _is_low_ocr_context(item: ContextItem) -> bool:
    return (
        item.ocr_confidence is not None
        and item.ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD
    )


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
    """Legacy check kept for backward compatibility. The new system
    prompt explicitly tells the LLM NOT to use rigid sections, so we
    don't gate on them anymore. Kept as a stub so older imports do not
    break."""
    return True


# Spanish-specific characters and common Spanish function words. The LLM
# usually answers in Spanish, so a long response with none of these is a strong
# signal that it replied in English (or another language).
_SPANISH_HINTS = ("ñ", "á", "é", "í", "ó", "ú", "ü", "¿", "¡",
                  " el ", " la ", " los ", " las ", " de ", " que ",
                  " con ", " para ", " por ", " según ", " documento",
                  " presupuesto", " pedido", " proveedor", " importe",
                  " no he ", " no hay ", " he encontrado")


def _response_looks_spanish(answer: str) -> bool:
    if not answer or len(answer) < 40:
        return False
    lowered = " " + answer.lower() + " "
    hint_count = sum(1 for hint in _SPANISH_HINTS if hint in lowered)
    # At least 2 Spanish hints, OR a Spanish-specific character anywhere.
    if any(ch in answer for ch in "ñáéíóúü¿¡"):
        return True
    return hint_count >= 2


def _question_is_spanish(question: str) -> bool:
    if any(ch in question for ch in "ñáéíóúü¿¡"):
        return True
    lowered = " " + question.lower() + " "
    return any(hint in lowered for hint in (" el ", " la ", " los ", " las ", " de ", " que "))


def _response_fabricates_documents(answer: str, context_items: list[ContextItem]) -> bool:
    """Reject the response if it mentions a plausible-looking filename that is
    not in the provided context (e.g. `pres_cliente_xyz.pdf`)."""
    if not context_items:
        return False
    # Build a set of normalised filenames from the context.
    known: set[str] = set()
    for item in context_items:
        for name in (item.document_filename, item.title):
            if name:
                known.add(name.lower())
                # Also keep the basename without extension.
                stem = name.rsplit(".", 1)[0].lower() if "." in name else name.lower()
                known.add(stem)
    # Look for any *.pdf / *.msg / *.docx reference in the response.
    found_refs = re.findall(r"[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|png|jpe?g|tiff?)\b", answer, flags=re.IGNORECASE)
    for ref in found_refs:
        ref_low = ref.lower()
        if not any(k in ref_low or ref_low in k for k in known):
            return True
    return False


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _extract_document_number(text: str) -> str | None:
    match = re.search(r"\b\d{4}/\d+\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b[A-Za-z]{0,8}\d{2,}[-/]\d+\b", text)
    if match:
        return match.group(0)
    # Pure numeric IDs (5-7 digits) that look like presupuesto / pedido numbers.
    match = re.search(r"\b\d{5,7}\b", text)
    return match.group(0) if match else None


_FILENAME_HINT = re.compile(
    r"\b[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|xls|xlsm|csv|tsv|png|jpe?g|tiff?|bmp|webp|eml|txt)\b",
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Follow-up suggestions
# ---------------------------------------------------------------------------

def _suggest_followups(
    question: str,
    resolved_doc_id: int | None,
    context_items: list[ContextItem],
) -> list[str]:
    """Generate 2-3 follow-up question suggestions based on the resolved
    document. We do this locally (no LLM call) so the cost stays negligible
    and the suggestions appear immediately when the response lands."""
    suggestions: list[str] = []
    if not context_items:
        return suggestions

    # Detect entity types from the context (no DB needed: we already
    # gathered the items and their summaries carry the relation labels).
    has_budget = any("presupuesto:" in it.summary.lower() or "presupuest" in it.title.lower() for it in context_items)
    has_order = any("pedido" in it.summary.lower() or "pedido" in it.title.lower() for it in context_items)
    has_invoice = any("factura" in it.summary.lower() or "factura" in it.title.lower() for it in context_items)
    has_aggregate = any("agregado" in it.title.lower() for it in context_items)
    relations = [it.summary for it in context_items if " → " in it.summary or "En la misma" in it.summary or "derivado" in it.summary or "paga" in it.summary or "origina" in it.summary]

    if resolved_doc_id is not None:
        if has_budget:
            suggestions.append("¿Cuánto se ha facturado ya de este presupuesto?")
            suggestions.append("¿Qué lineas tiene este presupuesto?")
        if has_order:
            suggestions.append("¿Cual es el importe total de este pedido con sus lineas?")
            suggestions.append("¿Hay factura que pague este pedido?")
        if has_invoice:
            suggestions.append("¿Que pedido origino esta factura?")
        if has_aggregate:
            suggestions.append("¿Podrias desglosarlo por proveedor?")
            suggestions.append("¿Y si lo limito al ultimo trimestre?")
        if not suggestions:
            suggestions.append("¿Que otros documentos hay en la misma carpeta?")
            suggestions.append("¿Hay mas detalles sobre el contenido?")
    else:
        normalized = _normalize(question)
        if has_aggregate or "total" in normalized or "cuanto" in normalized:
            suggestions.append("¿Podrias desglosarlo por proveedor?")
            suggestions.append("¿Y si lo limito al ultimo trimestre?")
        elif "presupuest" in normalized:
            suggestions.append("¿Que pedidos estan pendientes de facturar?")
            suggestions.append("¿Cuanto suman los presupuestos aceptados?")
        elif "pedido" in normalized:
            suggestions.append("¿Que proveedor tiene mas pedidos en curso?")
        else:
            suggestions.append("¿Cuales son los ultimos presupuestos aceptados?")

    # Deduplicate and cap at 3.
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
        if len(out) >= 3:
            break
    return out


# ---------------------------------------------------------------------------
# Conversation memory
# ---------------------------------------------------------------------------

# Heuristics: short follow-up questions that need context from the prior turn.
_FOLLOWUP_HINTS = (
    " y ", " y la", " y las", " y los", " y el", " y del", " y de la",
    "que pasa con", "qué pasa con", "del mismo", "de la misma",
    "de ese", "de esa", "esos mismos", "esas mismas",
    "tambien", "también", "ahora dime", "y cuanto", "y cuántos",
)


def _looks_like_followup(question: str) -> bool:
    """Return True if the question is short and looks like a follow-up that
    needs context from the previous turn."""
    q = (question or "").strip().lower()
    if len(q) > 110:
        return False
    if not q:
        return False
    return any(h in q for h in _FOLLOWUP_HINTS)


def _build_memory_block(db: Session, user: User, question: str, limit: int = 3) -> str | None:
    """For short follow-up questions, pull the last `limit` AIAnswers and
    summarise the entities they referenced. This lets the LLM resolve
    pronouns like 'y las facturas?' to the specific presupuesto / pedido
    that the previous turn was about."""
    if not _looks_like_followup(question):
        return None
    recent = list(
        db.scalars(
            select(AIAnswer)
            .join(AIQuestion, AIQuestion.id == AIAnswer.question_id)
            .where(AIQuestion.user_id == user.id)
            .order_by(AIAnswer.id.desc())
            .limit(limit)
        ).all()
    )
    if not recent:
        return None

    lines: list[str] = ["En los turnos anteriores de esta conversacion se mencionaron:"]
    for ans in reversed(recent):  # chronological order
        snippet = ans.answer.strip().split("\n")[0][:200] if ans.answer else ""
        entities: list[str] = []
        if ans.resolved_document_json:
            try:
                import json
                payload = json.loads(ans.resolved_document_json)
                doc = (payload or {}).get("document") or {}
                ent = doc.get("entities") or {}
                if ent.get("budget"):
                    b = ent["budget"]
                    if b.get("number"):
                        entities.append(f"presupuesto {b['number']}")
                    if b.get("client"):
                        entities.append(f"cliente {b['client']}")
                if ent.get("order"):
                    o = ent["order"]
                    if o.get("number"):
                        entities.append(f"pedido {o['number']}")
                    if o.get("supplier"):
                        entities.append(f"proveedor {o['supplier']}")
                if ent.get("invoice"):
                    i = ent["invoice"]
                    if i.get("number"):
                        entities.append(f"factura {i['number']}")
                if ent.get("plan"):
                    p = ent["plan"]
                    if p.get("project_name"):
                        entities.append(f"proyecto {p['project_name']}")
                if doc.get("filename"):
                    entities.append(f"archivo {doc['filename']}")
            except Exception:
                pass
        if entities:
            lines.append("- " + ", ".join(entities))
        elif snippet:
            lines.append(f"- (resumen) {snippet}")
    if len(lines) == 1:
        return None
    return "\n".join(lines)


def _extract_filenames(text: str) -> list[str]:
    """Find filename-like tokens in the user's question. Stops common false
    positives like URLs by requiring a document extension at the end."""
    return _FILENAME_HINT.findall(text or "")


# Re-export the money filter helper from the tools module so other code
# in this file can call it without a circular import.
_money_filters = _money_filters_internal


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
