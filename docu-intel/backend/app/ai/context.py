"""Context collection, rendering, and grounding for the AI agent.

This module owns the **what to tell the LLM** part of the agent
contract. It is the largest piece of the refactored agent stack
because the context-building logic itself is non-trivial:

- 14 distinct tools can each contribute items in different ways.
- Items must be deduplicated and redaction-filtered.
- The grounded fallback response must be coherent even when the
  LLM is unavailable or rejects the call.
- A handful of small formatters (``_format_source``,
  ``clip_excerpt``, ``_confidence_label``) are needed everywhere.

By keeping them all in one module we can read the **whole context
pipeline** in one pass. Previously these helpers were sprinkled
across a 1500-line file alongside the LLM client and the system
prompt, which made it impossible to test the rendering in isolation
without spinning up a full DB session.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Document, Order, OrderLine
from app.services.redaction import redact_sensitive_text
from app.services.tenant_access import (
    AccessScope,
    access_scope_cache_key,
    filter_documents_for_scope,
    filter_records_by_document_scope,
    filter_search_results_for_scope,
    filter_document_ids_for_scope,
)
from app.tools import internal

from .tools import ToolCall, _extract_document_number, _extract_room_name, _normalize


# ---------------------------------------------------------------------------
# Public dataclasses (re-exported by agent.py for backward compat)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextItem:
    """A single piece of context fed to the LLM.

    The fields are intentionally flat and string-friendly: any
    of them can be None, and the formatters handle the missing
    case by printing ``-``.
    """

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
    """The backend-built answer that the LLM call is expected to
    improve on (or replace). It carries its own confidence and
    model name so the caller can attribute the output even when
    the LLM is misconfigured or times out."""

    answer: str
    confidence: float
    model_name: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of context items the LLM ever sees. We slice the
# list in two places (collect_context, the prompt builder) so the
# LLM-side cap is what the prompt is told.
MAX_CONTEXT_ITEMS = 14

# Confidence threshold below which an OCR page is flagged as
# dubious. Used both in the prompt marker and in the warning
# builder.
LOW_OCR_CONFIDENCE_THRESHOLD = 0.70

# Tag inserted into the context line when an item is below the OCR
# confidence threshold. The LLM prompt is told to warn the user
# when this tag is present.
LOW_OCR_MARKER = "[OCR DUDOSO]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_context_items_for_scope(
    items: list[ContextItem],
    access_scope: AccessScope,
) -> list[ContextItem]:
    """Apply price/amount redaction to context items when the user
    is not authorised to see them.

    Items are returned as new dataclass instances (the original
    list is untouched — ContextItem is frozen).
    """
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
    """Run each tool in ``tools`` and collect the resulting context.

    Returns ``(context_items, warnings, resolved_document_id)``.

    ``resolved_document_id`` is set when the user mentioned a
    specific file and we successfully resolved it; the caller uses
    it to snapshot entities + relations onto the AIAnswer row for
    the UI.
    """
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
            summary = render_document_details(details)
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
                    summary = entry["label"] + "\n" + render_document_details(detail)
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
            context.extend(budget_context(db, budget) for budget in budgets)
        elif tool.name == "get_order_by_number":
            order_number = tool.arguments.get("order_number") or _extract_document_number(question)
            if not order_number:
                warnings.append("No se ha detectado un numero de pedido en la pregunta.")
                continue
            order = internal.get_order_by_number(db, order_number)
            if order and access_scope:
                order = filter_records_by_document_scope(db, [order], access_scope)[0] if filter_records_by_document_scope(db, [order], access_scope) else None
            if order:
                context.append(order_context(db, order, include_lines=True))
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
                context.append(budget_context(db, budget))
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
            context.extend(document_context(document, "Documento duplicado") for document in documents)
        elif tool.name == "get_ocr_review_documents":
            documents = internal.get_ocr_review_documents(db)
            if access_scope:
                documents = filter_documents_for_scope(db, documents, access_scope)
            context.extend(document_context(document, "Documento con error o revision OCR") for document in documents)
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
    return context[:MAX_CONTEXT_ITEMS], warnings, resolved_doc_id


def render_document_details(details: dict) -> str:
    """Render a ``get_document_full_details`` payload as a short, structured,
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
    """Build the fallback answer that the LLM call is supposed to
    improve on. When the LLM is unavailable or rejects the
    question, this is what the user sees.

    The text is intentionally conversational: the system prompt
    tells the LLM to talk the same way, so the user cannot tell
    whether the answer was generated by the backend or the model.
    """
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
    quote = clip_excerpt(raw_text, 600)
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


# ---------------------------------------------------------------------------
# Per-entity ContextItem builders
# ---------------------------------------------------------------------------


def budget_context(db: Session, budget: Budget) -> ContextItem:
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


def order_context(db: Session, order: Order, *, include_lines: bool = False) -> ContextItem:
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


def document_context(document: Document, prefix: str) -> ContextItem:
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


# ---------------------------------------------------------------------------
# Source deduplication and formatters
# ---------------------------------------------------------------------------


def dedupe_sources(items: list[ContextItem]) -> list[ContextItem]:
    """Drop duplicate (doc, page, block) tuples and items without a
    document_id, then cap at 10."""
    seen: set[tuple[int | None, int | None, int | None]] = set()
    sources: list[ContextItem] = []
    for item in items:
        key = (item.document_id, item.page_number, item.block_id)
        if key in seen or item.document_id is None:
            continue
        seen.add(key)
        sources.append(item)
    return sources[:10]


def format_source(item: ContextItem) -> str:
    """One-line citation: ``filename, pagina N`` or just ``filename``."""
    filename = item.document_filename or item.title
    page = f", pagina {item.page_number}" if item.page_number else ""
    return f"{filename}{page}"


# Backward-compatible alias. The prompts module and the original
# ``agent.py`` both used the underscore-prefixed name. New code
# should import ``format_source`` (the canonical, unprefixed name).
_format_source = format_source


def clip_excerpt(text: str, max_chars: int) -> str:
    """Trim the excerpt at a sentence boundary if possible, appending
    an ellipsis. We try each terminator (``. ``, ``; ``, ``: ``) and
    cut at the last one that is at least 60% into the window so we
    don't end up with a tiny fragment."""
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    for terminator in (". ", "; ", ": "):
        idx = clipped.rfind(terminator)
        if idx > max_chars * 0.6:
            return clipped[: idx + 1].rstrip() + "…"
    return clipped.rstrip() + "…"


def warning_lines(items: list[ContextItem], warnings: list[str]) -> str:
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
    """Average confidence across the items. When no item carries a
    confidence, fall back to the relevance score; when even that is
    missing, return 0.55 (the "we tried but we don't know" default)."""
    values = [item.confidence for item in items if item.confidence is not None]
    if not values:
        values = [item.relevance_score for item in items if item.relevance_score is not None]
    if not values:
        return 0.55
    return max(0.0, min(1.0, sum(values) / len(values)))


def confidence_label(value: float) -> str:
    if value >= 0.8:
        return "Alta"
    if value >= 0.5:
        return "Media"
    return "Baja"
