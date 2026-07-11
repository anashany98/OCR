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

import json
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Budget, Document, Order, OrderLine
from app.services.business_redaction import redact_business_payload_for_scope
from app.services.redaction import redact_sensitive_text
from app.services.tenant_access import (
    AccessScope,
    access_scope_cache_key,
    filter_document_ids_for_scope,
    filter_documents_for_scope,
    filter_records_by_document_scope,
    filter_search_results_for_scope,
)
from app.tools import internal

from .multi_query import expand_numbered_query, generate_query_variations
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
#
# Restored to 0.70 (was 0.60): a 0.60 threshold missed genuinely
# dubious OCR (mid-confidence scans with garbled tokens that the LLM
# then presented as fact). 0.70 surfaces those readings so the answer
# can carry an "[OCR DUDOSO]" caveat.
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

    def _check_scope(payload: dict) -> dict:
        """F0-04: reject payload if its document_id is not in scope."""
        if access_scope is None or access_scope.is_admin:
            return payload
        doc_id = payload.get("document_id")
        if doc_id is None:
            return payload
        allowed = filter_document_ids_for_scope(db, [doc_id], access_scope)
        if doc_id not in allowed:
            return {"found": False, "budget_number": payload.get("budget_number"),
                    "reason": "no autorizado"}
        return payload

    for tool in tools:
        if tool.name == "get_budget_total":
            payload = internal.get_budget_total(
                db,
                budget_number=tool.arguments.get("budget_number") or None,
                budget_id=tool.arguments.get("budget_id"),
            )
            payload = _check_scope(payload)
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=f"Total presupuesto {payload.get('budget_number') or 'indicado'}",
                )
            )
            if not payload.get("found"):
                warnings.append(
                    "No he encontrado el presupuesto "
                    f"{payload.get('budget_number') or 'indicado'} en las tablas estructuradas."
                )
        elif tool.name == "get_budget_lines":
            payload = internal.get_budget_lines(
                db,
                budget_number=tool.arguments.get("budget_number") or None,
                budget_id=tool.arguments.get("budget_id"),
            )
            payload = _check_scope(payload)
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=(
                        f"Lineas presupuesto {payload.get('budget_number')} "
                        f"({len(payload.get('lines') or [])} lineas)"
                    ),
                )
            )
        elif tool.name == "get_invoiced_amount_for_budget":
            payload = internal.get_invoiced_amount_for_budget(
                db,
                budget_number=tool.arguments.get("budget_number") or None,
                budget_id=tool.arguments.get("budget_id"),
            )
            payload = _check_scope(payload)
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=f"Facturado presupuesto {payload.get('budget_number') or 'indicado'}",
                )
            )
        elif tool.name == "list_recent_accepted_budgets":
            payload = internal.list_recent_accepted_budgets(
                db, limit=int(tool.arguments.get("limit") or 10)
            )
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=(f"Presupuestos aceptados recientes ({payload.get('count')})"),
                )
            )
        elif tool.name == "get_invoice_origin_order":
            payload = internal.get_invoice_origin_order(
                db,
                invoice_number=tool.arguments.get("invoice_number") or None,
                invoice_id=tool.arguments.get("invoice_id"),
            )
            payload = _check_scope(payload)
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=f"Origen factura {payload.get('invoice_number') or 'indicada'}",
                )
            )
        elif tool.name == "find_delivery_note_in_scope":
            payload = internal.find_delivery_note_in_scope(
                db,
                budget_number=tool.arguments.get("budget_number") or None,
                folder_path=tool.arguments.get("folder_path") or None,
                source_path_like=tool.arguments.get("source_path_like") or None,
            )
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=(
                        f"Albaranes en ambito {payload.get('scope')}"
                        if payload.get("scope")
                        else "Albaranes en ambito activo"
                    ),
                )
            )
            if not payload.get("found"):
                warnings.append(
                    "No he encontrado un albaran dentro del ambito activo. "
                    "Si quieres buscar en todos los documentos dilo explicitamente."
                )
        elif tool.name == "find_shipping_cost_in_scope":
            payload = internal.find_shipping_cost_in_scope(
                db,
                budget_number=tool.arguments.get("budget_number") or None,
                folder_path=tool.arguments.get("folder_path") or None,
                source_path_like=tool.arguments.get("source_path_like") or None,
            )
            context.append(
                _structured_context_item(
                    tool_name=tool.name,
                    payload=payload,
                    label=(f"Costes de envio en ambito {payload.get('scope')}"),
                )
            )
            if not payload.get("found"):
                warnings.append("No he encontrado conceptos de envio dentro del ambito activo.")
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
                        "Si querias otro, dime el nombre exacto."
                    )
            else:
                warnings.append(
                    f"No he encontrado ningun documento cuyo nombre contenga '{query}'."
                )
        elif tool.name == "get_document_full_details":
            if resolved_doc_id is None:
                # Skip silently if the lookup didn't resolve a document.
                continue
            details = internal.get_document_full_details(db, resolved_doc_id)
            if details is None:
                continue
            details = redact_business_payload_for_scope(details, access_scope)
            summary = render_document_details(details)
            # If the vision model described the image, prepend that
            # description to the summary so the LLM uses the actual visual
            # content (not just bad OCR) when explaining the file.
            vision = details.get("vision")
            if vision and vision.get("description"):
                summary = (
                    f"Vision aplicada ({vision.get('model', 'vision')}):\n"
                    f"{vision['description']}\n\n" + summary
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
                    r
                    for r in related
                    if filter_documents_for_scope(db, [r["document"]], access_scope)
                ]
            for entry in related:
                doc = entry["document"]
                # Multi-hop: for strong relations (depth 1) include the
                # related doc's own entities so the LLM has a full picture.
                detail = internal.get_document_full_details(db, doc.id)
                if detail is not None:
                    detail = redact_business_payload_for_scope(detail, access_scope)
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
                order = (
                    filter_records_by_document_scope(db, [order], access_scope)[0]
                    if filter_records_by_document_scope(db, [order], access_scope)
                    else None
                )
            if order:
                context.append(order_context(db, order, include_lines=True))
                if order.document_id:
                    resolved_doc_id = order.document_id
        elif tool.name == "get_budget_by_number":
            budget_number = tool.arguments.get("budget_number") or _extract_document_number(
                question
            )
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
                # CR4: Fallback to exact content search when structured
                # table has no match. This finds documents where the
                # number appears in text, entities, or filename even
                # when no Budget row exists.
                from app.services.exact_document_search import (
                    ExactMatch,
                    detect_identifiers,
                    search_exact_by_number,
                    select_best_exact_match,
                )
                try:
                    from app.services.metrics import EXACT_SEARCH
                except ImportError:  # metrics must never break retrieval
                    EXACT_SEARCH = None

                exact_matches = search_exact_by_number(
                    db,
                    number=budget_number,
                    kind="budget",
                    limit=5,
                    access_scope=access_scope,
                )
                if exact_matches:
                    best = select_best_exact_match(exact_matches, question_kind="budget")
                    if best:
                        resolved_doc_id = best.document_id
                        doc_row = db.get(Document, best.document_id)
                        if doc_row:
                            if EXACT_SEARCH is not None:
                                EXACT_SEARCH.labels(kind="budget", outcome="found").inc()
                            context.append(
                                ContextItem(
                                    title=f"Documento encontrado por numero exacto: {best.original_filename}",
                                    summary=(
                                        f"El numero '{budget_number}' aparece en el documento "
                                        f"(coincidencia en: {best.matched_in}). "
                                        f"Tipo: {best.document_type or doc_row.document_type} | "
                                        f"Estado: {doc_row.status}"
                                        + (f" | Ruta: {best.source_path}" if best.source_path else "")
                                    ),
                                    document_id=best.document_id,
                                    document_filename=best.original_filename,
                                    page_number=best.page_number,
                                    relevance_score=0.99,
                                    excerpt=None,
                                    confidence=doc_row.confidence,
                                    source_path=best.source_path,
                                )
                            )
                            warnings.append(
                                f"No hay fila estructurada como presupuesto para '{budget_number}', "
                                f"pero el numero aparece en el documento {best.original_filename}."
                            )
                        else:
                            if EXACT_SEARCH is not None:
                                EXACT_SEARCH.labels(kind="budget", outcome="doc_deleted").inc()
                else:
                    if EXACT_SEARCH is not None:
                        EXACT_SEARCH.labels(kind="budget", outcome="not_found").inc()
                # Also try filename search as secondary fallback
                documents = internal.find_document_by_filename(db, budget_number)
                if access_scope:
                    documents = filter_documents_for_scope(db, documents, access_scope)
                if documents:
                    resolved = documents[0]
                    resolved_doc_id = resolved.id
                    context.append(
                        ContextItem(
                            title=f"Documento presupuesto: {resolved.original_filename}",
                            summary=(
                                f"No hay fila estructurada en presupuestos para '{budget_number}', "
                                "pero si hay un documento cuyo nombre/ruta coincide. "
                                f"Tipo: {resolved.document_type} | Estado: {resolved.status} | "
                                f"Confianza: {resolved.confidence} | Paginas: {resolved.page_count} | "
                                f"Ruta: {resolved.source_path}"
                            ),
                            document_id=resolved.id,
                            document_filename=resolved.original_filename,
                            page_number=None,
                            relevance_score=0.99,
                            excerpt=None,
                            confidence=resolved.confidence,
                            source_path=resolved.source_path,
                        )
                    )
                    warnings.append(
                        f"El presupuesto '{budget_number}' no esta en la tabla estructurada; "
                        "uso el documento coincidente por nombre/ruta."
                    )
                else:
                    warnings.append(
                        "No he encontrado ningun presupuesto ni documento con numero "
                        f"'{budget_number}'. Prueba a buscar por nombre de archivo o por "
                        "importe/cliente."
                    )
        elif tool.name == "aggregate_business":
            entity = tool.arguments.get("entity") or "order"
            kind = tool.arguments.get("kind") or "count"
            result = internal.aggregate_business(
                db, entity=entity, kind=kind, query=question, access_scope=access_scope
            )
            rows = result.get("rows") or []
            filters = result.get("filters") or {}
            summary_lines = [
                f"Agregado: {result.get('entity')} / {result.get('kind')}",
            ]
            if result.get("price_redacted"):
                summary_lines.append("Importes ocultos por la politica de acceso.")
            if filters:
                fl = ", ".join(f"{k}={v}" for k, v in filters.items())
                summary_lines.append(f"Filtros aplicados: {fl}")
            summary_lines.append(f"Resultados: {len(rows)}")
            # Render the per-row data as a clean Markdown table so both
            # the LLM and the grounded fallback see a structured form
            # (not the legacy ``label - value - estado`` string).
            table_md = _render_aggregate_table(entity, kind, rows)
            if table_md:
                summary_lines.append("")
                summary_lines.append(table_md)
            rendered = "\n".join(summary_lines)
            context.append(
                ContextItem(
                    title=f"Agregado {entity}/{kind}",
                    summary=rendered,
                    document_id=None,
                    document_filename=None,
                    page_number=None,
                    relevance_score=1.0,
                    excerpt=rendered,
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

            # Multi-query: run the original + N variations, then
            # merge via score-weighted dedup. This improves recall
            # when the user's phrasing differs from the document's.
            variations = generate_query_variations(query)
            numbered = expand_numbered_query(query)
            all_variations = variations + [v for v in numbered if v.text != query]

            # Deduplicate by text (keep highest weight)
            seen: dict[str, float] = {}
            for v in all_variations:
                key = v.text.lower().strip()
                if key not in seen or v.weight > seen[key]:
                    seen[key] = v.weight

            # Run search for each unique variation

            merged_scores: dict[tuple, float] = {}
            merged_results: dict[tuple, Any] = {}
            for variant_text, weight in seen.items():
                try:
                    variant_results = internal.hybrid_search(
                        db, variant_text, filters
                    )
                    for rank, r in enumerate(variant_results):
                        if r.document_id is None:
                            continue
                        key = (r.document_id, r.page_number, r.block_id, r.chunk_id)
                        # RRF-style score: weight / (k + rank). Use the
                        # same RRF constant as the standalone hybrid search so
                        # in-agent and out-of-agent ranking stay consistent.
                        rrf_score = weight / (settings.search_rrf_k + rank + 1)
                        if key in merged_scores:
                            merged_scores[key] += rrf_score
                        else:
                            merged_scores[key] = rrf_score
                            merged_results[key] = r
                except Exception:
                    continue  # best-effort: skip failed variations

            # Sort by merged score and take top results
            ranked_keys = sorted(merged_scores, key=merged_scores.get, reverse=True)
            limit_val = int(filters.get("limit", 8))
            results = []
            for key in ranked_keys[:limit_val]:
                r = merged_results[key]
                # Update score to reflect multi-query ranking
                from dataclasses import replace

                results.append(replace(r, score=merged_scores[key]))

            if access_scope:
                results = filter_search_results_for_scope(db, results, access_scope)
            # Merge results that come from the same document: concatenate
            # their excerpts so the LLM sees the full document body
            # rather than a single chunk. This is critical for short
            # documents (emails, single-page PDFs) where the
            # top-ranked chunk is only a fraction of the relevant text.
            per_doc_excerpts: dict[int, list[str]] = {}
            per_doc_top: dict[int, Any] = {}
            for r in results:
                if r.document_id is None:
                    continue
                per_doc_top.setdefault(r.document_id, r)
                excerpt = r.excerpt or ""
                if excerpt and excerpt not in per_doc_excerpts.setdefault(r.document_id, []):
                    per_doc_excerpts[r.document_id].append(excerpt)
            for doc_id, top in per_doc_top.items():
                chunks = per_doc_excerpts.get(doc_id, [])
                # Filter out trivial/empty chunks that waste context space.
                # Patterns: empty Excel sheets, pages with no extracted text.
                _EMPTY_PATTERNS = ("(Hoja sin datos)", "(Sheet sin datos)", "Hoja sin datos")
                chunks = [
                    c for c in chunks
                    if len(c.strip()) > 50 and not any(p in c for p in _EMPTY_PATTERNS)
                ]
                if not chunks:
                    continue
                # If the search only returned one chunk AND the
                # document is short (< 1500 chars of text), fetch
                # the full OCR text of the document and use that
                # instead. This avoids the LLM only seeing the
                # bottom of an email because the chunker split it
                # unevenly.
                if len(chunks) == 1:
                    full_text = _fetch_full_document_text(db, doc_id, top.page_number)
                    if full_text and len(full_text) > len(chunks[0]):
                        chunks = [full_text]
                combined = " | ".join(chunks[:4])
                if len(combined) > 4000:
                    combined = combined[:4000] + "…"
                context.append(
                    ContextItem(
                        title=top.original_filename,
                        summary=combined,
                        document_id=top.document_id,
                        document_filename=top.original_filename,
                        page_number=top.page_number,
                        block_id=top.block_id,
                        relevance_score=top.score,
                        excerpt=combined,
                        confidence=top.ocr_confidence,
                        ocr_confidence=top.ocr_confidence,
                        source_path=top.source_path,
                    )
                )
        elif tool.name == "get_duplicate_documents":
            documents = internal.get_duplicate_documents(db)
            if access_scope:
                documents = filter_documents_for_scope(db, documents, access_scope)
            context.extend(
                document_context(document, "Documento duplicado") for document in documents
            )
        elif tool.name == "get_ocr_review_documents":
            documents = internal.get_ocr_review_documents(db)
            if access_scope:
                documents = filter_documents_for_scope(db, documents, access_scope)
            context.extend(
                document_context(document, "Documento con error o revision OCR")
                for document in documents
            )
        elif tool.name == "search_entities":
            entities = internal.search_entities(
                db,
                entity_type=tool.arguments.get("entity_type") or "reference",
                value=tool.arguments.get("value") or question,
            )
            if access_scope:
                allowed_ids = filter_document_ids_for_scope(
                    db, [entity.document_id for entity in entities], access_scope
                )
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
            room_name = (
                tool.arguments.get("room_name")
                or _extract_room_name(_normalize(question))
                or question
            )
            rows = internal.search_plan_room_measurements(db, room_name)
            if access_scope:
                allowed_ids = filter_document_ids_for_scope(
                    db, [document.id for _, _, document in rows], access_scope
                )
                rows = [
                    (plan, room, document)
                    for plan, room, document in rows
                    if document.id in allowed_ids
                ]
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
                    warnings.append(
                        f"La estancia {room.name or room_name} requiere revision manual."
                    )
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

    if not context and any(
        tool.name == "hybrid_search"
        and tool.arguments.get("filters", {}).get("document_type") == "plano"
        for tool in tools
    ):
        warnings.append(
            "No hay datos de planos suficientes. Si la pregunta requiere convertir medidas, se necesita escala valida o cota fiable."
        )
    if not context and any(tool.name == "search_plan_room_measurements" for tool in tools):
        warnings.append("No hay habitaciones con medidas verificables para esa consulta.")
    if not context and any(tool.name == "get_related_documents" for tool in tools):
        warnings.append(
            "El documento no tiene vinculos conocidos con otros documentos del proyecto."
        )
    # CR7: When an exact match resolved a document, ensure its page text
    # is loaded into the context so the LLM can cite specific content.
    # For short documents (< 5 pages), load all pages. For long ones,
    # load only the matching page + adjacent pages.
    if resolved_doc_id is not None:
        _maybe_load_resolved_document_text(
            db, resolved_doc_id, context, warnings, access_scope=access_scope
        )
    return context[:MAX_CONTEXT_ITEMS], warnings, resolved_doc_id


def _maybe_load_resolved_document_text(
    db: Session,
    doc_id: int,
    context: list,
    warnings: list,
    *,
    access_scope: AccessScope | None,
) -> None:
    """Load page text for the resolved document if not already present.

    If the context already contains items from this document (from
    get_document_full_details or search results), skip to avoid
    duplication. Otherwise, load the page text and add it as a
    context item so the LLM has the raw content to cite.
    """
    from app.models import DocumentPage

    # Check if context already has items from this document
    already_loaded = any(
        getattr(item, "document_id", None) == doc_id for item in context
    )
    if already_loaded:
        return

    doc = db.get(Document, doc_id)
    if not doc:
        return

    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == doc_id)
            .order_by(DocumentPage.page_number.asc())
        ).all()
    )
    if not pages:
        return

    # For short documents, load all pages; for long ones, load first 3
    max_pages = 3 if len(pages) > 5 else len(pages)
    text_parts = []
    for page in pages[:max_pages]:
        page_text = (page.text or "").strip()
        if page_text:
            text_parts.append(f"[Pagina {page.page_number}]\n{page_text}")

    if text_parts:
        full_text = "\n\n".join(text_parts)
        context.append(
            ContextItem(
                title=f"Texto del documento: {doc.original_filename}",
                summary=full_text[:2000],
                document_id=doc.id,
                document_filename=doc.original_filename,
                page_number=1,
                relevance_score=0.98,
                excerpt=full_text[:500],
                confidence=doc.confidence,
                source_path=doc.source_path if access_scope and access_scope.is_admin else None,
            )
        )


def render_document_details(details: dict) -> str:
    """Render a ``get_document_full_details`` payload as a short, structured,
    human-readable string that the LLM can use as a grounding fact-sheet."""
    lines: list[str] = []
    entities = details.get("entities") or {}

    if "budget" in entities:
        b = entities["budget"]
        parts = [
            p
            for p in [
                f"numero {b.get('number')}" if b.get("number") else None,
                f"cliente {b.get('client')}" if b.get("client") else None,
                f"importe {b.get('total_amount')} {b.get('currency') or ''}".strip()
                if b.get("total_amount") is not None
                else None,
                f"fecha {b.get('date')}" if b.get("date") else None,
                f"estado {b.get('status')}" if b.get("status") else None,
                "aceptado" if b.get("accepted") else "no aceptado",
            ]
            if p
        ]
        if parts:
            lines.append("Presupuesto: " + " | ".join(parts))
        if b.get("line_count"):
            lines.append(f"  lineas: {b['line_count']}")
        for ln in b.get("lines_preview") or []:
            ref = ln.get("reference") or "-"
            desc = (ln.get("description") or "").strip()[:80]
            qty = ln.get("quantity")
            tot = ln.get("total_price")
            lines.append(
                f"    - {ref} {desc} x{qty if qty is not None else '-'} total {tot if tot is not None else '-'}"
            )

    if "order" in entities:
        o = entities["order"]
        parts = [
            p
            for p in [
                f"numero {o.get('number')}" if o.get("number") else None,
                f"proveedor {o.get('supplier')}" if o.get("supplier") else None,
                f"cliente {o.get('client')}" if o.get("client") else None,
                f"importe {o.get('total_amount')} {o.get('currency') or ''}".strip()
                if o.get("total_amount") is not None
                else None,
                f"fecha {o.get('date')}" if o.get("date") else None,
            ]
            if p
        ]
        if parts:
            lines.append("Pedido: " + " | ".join(parts))
        if o.get("related_budget_id"):
            lines.append(f"  derivado del presupuesto id={o['related_budget_id']}")
        if o.get("line_count"):
            lines.append(f"  lineas: {o['line_count']}")

    if "invoice" in entities:
        i = entities["invoice"]
        parts = [
            p
            for p in [
                f"numero {i.get('number')}" if i.get("number") else None,
                f"proveedor {i.get('supplier')}" if i.get("supplier") else None,
                f"cliente {i.get('client')}" if i.get("client") else None,
                f"importe {i.get('total_amount')} {i.get('currency') or ''}".strip()
                if i.get("total_amount") is not None
                else None,
                f"fecha {i.get('date')}" if i.get("date") else None,
            ]
            if p
        ]
        if parts:
            lines.append("Factura: " + " | ".join(parts))

    if "plan" in entities:
        pl = entities["plan"]
        parts = [
            p
            for p in [
                f"proyecto {pl.get('project_name')}" if pl.get("project_name") else None,
                f"escala {pl.get('scale_text')}" if pl.get("scale_text") else None,
                "escala valida" if pl.get("has_valid_scale") else "escala no valida",
                f"unidad {pl.get('unit')}" if pl.get("unit") else None,
            ]
            if p
        ]
        if parts:
            lines.append("Plano: " + " | ".join(parts))
        for r in pl.get("rooms_preview") or []:
            lines.append(
                f"    - estancia {r.get('name') or '-'}: area {r.get('area_m2')} m2"
                if r.get("area_m2") is not None
                else f"    - estancia {r.get('name') or '-'}: sin medidas"
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

    Tono: estilo ChatGPT — amable, estructurado, directo. Sin secciones
    obligatorias tipo "Respuesta/Datos/Fuentes/Confianza" (el frontend
    ya muestra la ficha tecnica). Sin formuletas tipo "Lo mas claro
    que he encontrado esta en...". La meta es que el usuario no
    detecte si la respuesta la escribio el modelo o el backend.

    CTX-7: when the top context item is a document we could resolve
    (a filename mention, a plan lookup) we detect the four business
    failure modes the user listed and produce a friendly explanation
    instead of the raw "Tipo: desconocido | Estado: duplicate |
    Confianza: None | Paginas: None" string the old code emitted.
    The friendly text is produced by :func:`_build_friendly_fallback`
    which is also called directly from the LLM path when the LLM
    output is rejected.
    """
    context_items = [
        item for item in context_items if item.title != "Memoria de la conversacion"
    ]
    if not context_items:
        # Natural-language "nothing found": 1-2 sentences, no bullet list.
        lead = (
            "No he encontrado informacion en el sistema para responder a eso. "
            "Si me das un numero de documento, un proveedor, un cliente, una fecha "
            "o el nombre de un archivo, lo busco mas a fondo."
        )
        return GroundedResponse(
            answer=lead,
            confidence=0.0,
            model_name="backend_grounded_fallback",
        )

    # CTX-7: detect business failure modes (duplicate, unknown type,
    # low OCR, no text) and produce a friendly explanation. The
    # friendly text replaces the raw metadata dump the previous
    # version emitted.
    friendly = _build_friendly_fallback(context_items, warnings)
    if friendly is not None:
        return friendly

    warnings = _warnings_with_low_ocr_notice(context_items, warnings)
    confidence = _average_confidence(context_items)
    top = context_items[0]
    # Structured-tool items carry an internal ``[Estructurado]`` prefix in
    # their title (used by the LLM detection in agent.has_answer_context).
    # Strip it for the user-facing label so the chat never exposes that
    # jargon; prefer the human-readable ``summary`` over raw JSON.
    raw_title = top.title or ""
    clean_title = (
        raw_title[len("[Estructurado] ") :].strip()
        if raw_title.startswith("[Estructurado] ")
        else raw_title
    )
    file_label = top.document_filename or clean_title or "el documento mas relevante"
    page_label = f", pagina {top.page_number}" if top.page_number else ""

    # For structured-tool items the ``excerpt`` is raw JSON (meant for the
    # LLM). The user should see the human-readable ``summary`` instead.
    if raw_title.startswith("[Estructurado] "):
        raw_text = (top.summary or top.excerpt or "").strip()
    else:
        raw_text = (top.summary or top.excerpt or "").strip()
    # Markdown tables (e.g. from ``aggregate_business`` tool results) are
    # rendered as-is: they read well as a table and would break inside prose.
    starts_table = raw_text.lstrip().startswith("|")
    aggregate_header_then_table = (
        raw_text.lstrip().startswith("Agregado:") and "\n|" in raw_text
    )
    is_table = starts_table or aggregate_header_then_table
    quote = clip_excerpt(raw_text, 600)

    if is_table:
        # Keep the table, but lead with a natural sentence, not a bare label.
        lead = f"Segun **{file_label}**{page_label}, esto es lo que aparece:\n\n{quote}"
    elif quote:
        # Quote the relevant excerpt as part of the answer, inline, not as a
        # blockquote. A single short line is woven into the sentence; a long
        # one goes on its own paragraph after a natural lead-in.
        lead = (
            f"En **{file_label}**{page_label} aparece este texto: {quote}"
            if len(quote) <= 160
            else f"En **{file_label}**{page_label} aparece lo siguiente:\n\n{quote}"
        )
    else:
        lead = (
            f"He encontrado **{file_label}**{page_label}, pero el texto recuperado "
            "no basta para responder con seguridad."
        )

    # Mention 1-2 additional sources only when they add value, woven into a
    # sentence rather than as a "Tambien he revisado:" list.
    extras: list[str] = []
    for item in context_items[1:3]:
        label = item.document_filename or item.title or "otro documento"
        if item.page_number:
            label += f", pagina {item.page_number}"
        extras.append(f"**{label}**")
    if extras:
        if len(extras) == 1:
            lead += f" Tambien aparece en {extras[0]}."
        else:
            lead += " Coincide ademas con lo que aparece en " + " y ".join(extras) + "."

    # Low-OCR / duplicate warnings are folded into the answer naturally as a
    # closing remark, not as an "Avisos:" block.
    if warnings:
        warning_phrase = "; ".join(warnings[:2]).strip().rstrip(".")
        lead += f" Ojo: {warning_phrase}."

    return GroundedResponse(
        answer=lead,
        confidence=confidence,
        model_name="backend_grounded_fallback",
    )


# ---------------------------------------------------------------------------
# CTX-7 — friendly fallback for business failure modes
# ---------------------------------------------------------------------------


def _build_friendly_fallback(
    context_items: list[ContextItem],
    warnings: list[str],
) -> GroundedResponse | None:
    """Return a business-language explanation when the top context
    item is a document in a known bad state.

    Returns ``None`` when the context is healthy and the regular
    fallback should be used. The detection rules:

    * ``status == "duplicate"`` → explain the duplicate + suggest the
      original document; mention related documents the user can jump
      to.
    * ``document_type == "desconocido"`` (or ``unknown``) → say the
      file is not classified yet, suggest reprocess.
    * OCR confidence below :data:`LOW_OCR_CONFIDENCE_THRESHOLD` → warn
      that the reading is unreliable and ask the user to reprocess.
    * No text extracted at all → say the OCR produced no usable text.
    """
    if not context_items:
        return None
    top = context_items[0]

    # Only trigger the friendly path when the top item is a resolved
    # document (we have a filename and the summary carries the
    # "Tipo: ... | Estado: ... | Confianza: ..." metadata the old
    # code emitted). Structured tools and pure text items pass
    # through to the regular fallback.
    summary = top.summary or ""
    is_resolved_document = (
        "Tipo:" in summary and "Estado:" in summary and top.document_id is not None
    )
    if not is_resolved_document:
        return None

    # Parse the metadata out of the summary produced by
    # ``collect_context``'s find_document_by_filename branch.
    meta = _parse_resolved_metadata(summary)

    # Duplicate document: the most common UX trap the user listed.
    if meta.get("status") == "duplicate":
        related = _related_filenames(context_items[1:6])
        if related:
            related_text = (
                "\n\nHe encontrado estos candidatos a ser el original: "
                + ", ".join(f"**{r}**" for r in related)
                + "."
            )
        else:
            related_text = ""
        answer = (
            "Este documento esta marcado como **duplicado**, asi que no tiene una "
            "extraccion OCR propia. El contenido util esta en el documento original "
            f"del que procede.{related_text} Te recomiendo abrir el original en lugar "
            "de este PDF."
        )
        return GroundedResponse(
            answer=answer,
            confidence=0.2,
            model_name="backend_grounded_fallback",
        )

    # Document not yet classified.
    if meta.get("document_type") in {"desconocido", "unknown"}:
        answer = (
            "Todavia no he clasificado este documento (sigue como tipo **desconocido**), "
            "asi que no puedo decirte de que trata con seguridad. Si lo re-procesas desde "
            "su ficha, el sistema lo catalogara y le aplicara la extraccion correspondiente."
        )
        return GroundedResponse(
            answer=answer,
            confidence=0.15,
            model_name="backend_grounded_fallback",
        )

    # Low OCR confidence.
    if meta.get("confidence_low") or _is_low_ocr_context(top):
        conf_pct = (
            int(round(float(top.confidence or 0) * 100)) if top.confidence is not None else None
        )
        conf_text = f" ({conf_pct}% de confianza OCR)" if conf_pct is not None else ""
        answer = (
            f"He encontrado el documento, pero el OCR tiene baja calidad{conf_text}. "
            "No puedo confirmar ese contenido con seguridad; re-procesalo y vuelvo a responder con la nueva lectura."
        )
        return GroundedResponse(
            answer=answer,
            confidence=0.2,
            model_name="backend_grounded_fallback",
        )

    # No text extracted at all.
    if not (top.excerpt or top.summary or "").strip():
        answer = (
            "He encontrado el documento pero el OCR no ha extraido texto util "
            "(puede que sea un PDF solo de imagen o que la extraccion haya fallado). "
            "Si lo re-procesas desde su ficha, tendre contenido con el que trabajar."
        )
        return GroundedResponse(
            answer=answer,
            confidence=0.1,
            model_name="backend_grounded_fallback",
        )

    return None


def _parse_resolved_metadata(summary: str) -> dict:
    """Parse the ``Tipo: X | Estado: Y | Confianza: Z | ...`` summary
    emitted by :func:`collect_context`'s find_document_by_filename branch.

    The parser is intentionally tolerant: missing keys become
    ``None``. The parser never raises.
    """
    out: dict = {
        "document_type": None,
        "status": None,
        "confidence": None,
        "page_count": None,
        "confidence_low": False,
    }
    if not summary:
        return out
    parts = [segment.strip() for segment in summary.split("|")]
    for segment in parts:
        if ":" not in segment:
            continue
        key, _, value = segment.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "tipo":
            out["document_type"] = value.lower()
        elif key == "estado":
            out["status"] = value.lower()
        elif key == "confianza":
            try:
                out["confidence"] = float(value)
            except (TypeError, ValueError):
                out["confidence"] = value
            if out["confidence"] is not None and isinstance(out["confidence"], float):
                out["confidence_low"] = out["confidence"] < LOW_OCR_CONFIDENCE_THRESHOLD
        elif key == "paginas":
            out["page_count"] = value
    return out


def _related_filenames(items: list[ContextItem]) -> list[str]:
    """Return the filenames of related context items (after the first)."""
    out: list[str] = []
    for item in items:
        name = item.document_filename or item.title
        if name and name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Per-entity ContextItem builders
# ---------------------------------------------------------------------------


def _fetch_full_document_text(
    db: Session, document_id: int, page_number: int | None
) -> str | None:
    """Return the full OCR text of a document (or a single page).

    Used as a fallback when the hybrid search only returned a partial
    chunk for a short document: a one-page email or a single-page
    contract often fits in a single chunk, but the chunking step
    truncated the body to the last paragraph, hiding the From / To /
    Subject headers. Falling back to the full page text makes the
    LLM see the whole document.
    """
    try:
        from app.models import DocumentPage

        stmt = select(DocumentPage.text).where(DocumentPage.document_id == document_id)
        if page_number is not None:
            stmt = stmt.where(DocumentPage.page_number == page_number)
        stmt = stmt.order_by(DocumentPage.page_number.asc())
        rows = db.execute(stmt).all()
    except Exception:
        return None
    parts = [text for (text,) in rows if text]
    if not parts:
        return None
    return "\n\n".join(parts)


def budget_context(db: Session, budget: Budget) -> ContextItem:
    document = db.get(Document, budget.document_id)
    amount = (
        f"{budget.total_amount:.2f} {budget.currency or ''}".strip()
        if budget.total_amount is not None
        else "importe no detectado"
    )
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
    amount = (
        f"{order.total_amount:.2f} {order.currency or ''}".strip()
        if order.total_amount is not None
        else "importe no detectado"
    )
    summary = f"Pedido {order.order_number or order.id} - Proveedor {order.supplier_name or '-'} - Cliente {order.client_name or '-'} - {amount}"
    if include_lines:
        lines = list(
            db.scalars(
                select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id.asc())
            ).all()
        )
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


def _structured_context_item(
    *,
    tool_name: str,
    payload: dict,
    label: str,
) -> ContextItem:
    """Render a structured-tool payload as a :class:`ContextItem`.

    The payload is rendered as human-readable text for the ``summary``
    (used in the grounded fallback) and kept as raw JSON in the
    ``excerpt`` (used in the LLM prompt, where the model can parse it).
    The relevance score is 1.0 because structured data is always
    authoritative when present.
    """
    import json

    raw_json = json.dumps(payload, default=str, ensure_ascii=False)
    human_readable = _render_structured_payload(tool_name, payload)
    found = bool(payload.get("found", True))
    confidence = float(payload.get("confidence") or (0.95 if found else 0.2))
    return ContextItem(
        title=f"[Estructurado] {label}",
        summary=human_readable,
        document_id=payload.get("document_id"),
        document_filename=None,
        page_number=None,
        relevance_score=1.0,
        excerpt=raw_json,
        confidence=confidence,
        source_path=None,
    )


def _structured_not_found_text(tool_name: str, payload: dict) -> str:
    """Natural-language "not found" sentence for a structured tool that
    reported ``found: false``.

    Replaces the old ``"Datos no encontrados para {tool_name}."`` leak,
    which exposed internal snake_case tool names to the user. Each tool
    gets a Spanish sentence phrased so it can be quoted directly in the
    chat answer.
    """
    if tool_name == "get_invoice_origin_order":
        num = payload.get("invoice_number")
        scope = f" {num}" if num else ""
        return (
            f"No he encontrado el pedido de origen de la factura{scope} en la base "
            "estructurada. Puede que la factura no este vinculada a ningun pedido."
        )
    if tool_name == "get_budget_total":
        num = payload.get("budget_number") or payload.get("budget_id")
        scope = f" {num}" if num else ""
        return (
            f"No he encontrado el importe total del presupuesto{scope} en la base "
            "estructurada."
        )
    if tool_name == "get_invoiced_amount_for_budget":
        num = payload.get("budget_number") or payload.get("budget_id")
        scope = f" {num}" if num else ""
        return (
            f"No he encontrado facturacion asociada al presupuesto{scope} en la base "
            "estructurada."
        )
    if tool_name == "get_budget_lines":
        num = payload.get("budget_number") or payload.get("budget_id")
        scope = f" {num}" if num else ""
        return f"No he encontrado las lineas del presupuesto{scope}."
    if tool_name == "list_recent_accepted_budgets":
        return "No he encontrado presupuestos aceptados recientes."
    if tool_name == "find_delivery_note_in_scope":
        return (
            "No he encontrado un albaran de entrega dentro del ambito de busqueda actual."
        )
    if tool_name == "find_shipping_cost_in_scope":
        return (
            "No he encontrado gastos de envio asociados dentro del ambito de busqueda actual."
        )
    # Generic fallback: never leak the raw tool name. Describe the entity
    # by the keys present (minus internal flags) so the sentence is useful.
    public = [
        f"{k}={v}"
        for k, v in payload.items()
        if k not in {"found", "confidence", "document_id"} and v not in (None, "", [])
    ]
    detail = f" ({', '.join(public[:3])})" if public else ""
    return f"No he encontrado ese dato en la base estructurada{detail}."


def _render_structured_payload(tool_name: str, payload: dict) -> str:
    """Convert a structured-tool JSON payload into human-readable text.

    This is used in the grounded fallback so users never see raw JSON
    or internal tool names. The LLM still receives the raw JSON in the
    excerpt field. When a tool reports ``found: false`` the text is a
    natural-language "not found" sentence per entity, phrased in
    Spanish so it can be quoted directly to the user.
    """
    if not payload.get("found", True):
        return _structured_not_found_text(tool_name, payload)

    parts: list[str] = []

    if tool_name in ("get_budget_total", "get_budget_lines", "get_invoiced_amount_for_budget"):
        num = payload.get("budget_number") or payload.get("budget_id") or "-"
        if "total_amount" in payload:
            amt = payload["total_amount"]
            cur = payload.get("currency") or ""
            parts.append(f"Presupuesto {num}: {amt} {cur}".strip())
        if "lines" in payload:
            lines = payload["lines"] or []
            parts.append(f"Lineas: {len(lines)}")
            for ln in lines[:8]:
                ref = ln.get("reference") or "-"
                desc = (ln.get("description") or "")[:60]
                qty = ln.get("quantity")
                tot = ln.get("total_price")
                parts.append(f"  - {ref} {desc} x{qty or '-'} total {tot or '-'}")
        if "client_name" in payload and payload["client_name"]:
            parts.append(f"Cliente: {payload['client_name']}")
        if "date" in payload and payload["date"]:
            parts.append(f"Fecha: {payload['date']}")
        if "status" in payload and payload["status"]:
            parts.append(f"Estado: {payload['status']}")

    elif tool_name == "list_recent_accepted_budgets":
        budgets = payload.get("budgets") or []
        parts.append(f"Presupuestos aceptados recientes: {len(budgets)}")
        for b in budgets:
            num = b.get("budget_number") or b.get("id") or "-"
            client = b.get("client_name") or "-"
            amt = b.get("total_amount")
            cur = b.get("currency") or ""
            date = b.get("date") or "-"
            amt_str = f" | {amt} {cur}" if amt else ""
            parts.append(f"  - {num} ({date}) cliente: {client}{amt_str}")

    elif tool_name == "get_invoice_origin_order":
        num = payload.get("invoice_number") or "-"
        if "order_number" in payload and payload["order_number"]:
            parts.append(f"Factura {num} proviene del pedido {payload['order_number']}")
        elif "supplier" in payload and payload["supplier"]:
            parts.append(f"Factura {num} de proveedor {payload['supplier']}")
        else:
            parts.append(f"Factura {num}: sin pedido de origen identificado")

    elif tool_name in ("find_delivery_note_in_scope", "find_shipping_cost_in_scope"):
        scope = payload.get("scope") or "-"
        found_items = payload.get("items") or []
        parts.append(f"Alcance: {scope} | Resultados: {len(found_items)}")
        for item in found_items[:5]:
            desc = item.get("description") or item.get("label") or str(item)[:100]
            parts.append(f"  - {desc}")

    else:
        # Generic: show key=value pairs
        for k, v in payload.items():
            if k in ("found", "confidence", "document_id"):
                continue
            if v is not None and v != "" and v != []:
                if isinstance(v, list) and len(v) > 3:
                    parts.append(f"{k}: {len(v)} elementos")
                elif isinstance(v, dict):
                    inner = ", ".join(f"{ik}={iv}" for ik, iv in v.items() if iv)
                    parts.append(f"{k}: {inner}")
                else:
                    parts.append(f"{k}: {v}")

    return "\n".join(parts) if parts else json.dumps(payload, default=str, ensure_ascii=False)


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
    text = text.strip()
    preserve_newlines = text.startswith("|") or (text.startswith("Agregado:") and "\n|" in text)
    if not preserve_newlines:
        text = text.replace("\n", " ")
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
    return item.ocr_confidence is not None and item.ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD


def _average_confidence(items: list[ContextItem]) -> float:
    """Compute a composite answer-confidence score from context items.

    Previously this just averaged ``ocr_confidence``, which made
    every answer look terrible (0.02-0.03) even when the LLM
    synthesized a solid answer from multiple sources.

    The new formula weights three independent signals:
      - **Source density** (0.35): more corroborating sources →
        higher confidence.  Saturates at ~6 sources.
      - **Relevance** (0.35): average search-relevance score.
        Hybrid search returns scores in ~[0, 1.5] via RRF; we
        normalise by capping at 1.0.
      - **OCR quality** (0.30): geometric mean of page OCR
        confidences.  We use the *minimum* rather than the mean
        so a single garbage page doesn't inflate the score, but
        a floor of 0.15 prevents a bad scan from tanking the
        whole answer when other signals are strong.
    """
    if not items:
        return 0.0

    # --- source density ---
    n = len(items)
    source_score = min(n / 6.0, 1.0)  # saturates at 6+

    # --- relevance ---
    rel_values = [
        min(item.relevance_score or 0.0, 1.0)
        for item in items
        if item.relevance_score is not None
    ]
    rel_score = (sum(rel_values) / len(rel_values)) if rel_values else 0.5

    # --- OCR quality ---
    ocr_values = [
        item.ocr_confidence
        for item in items
        if item.ocr_confidence is not None
    ]
    if ocr_values:
        # geometric mean, floored at 0.15
        product = 1.0
        for v in ocr_values:
            product *= max(v, 0.15)
        ocr_score = product ** (1.0 / len(ocr_values))
    else:
        ocr_score = 0.5  # unknown OCR quality → neutral

    composite = 0.35 * source_score + 0.35 * rel_score + 0.30 * ocr_score
    return round(max(0.0, min(1.0, composite)), 3)


def confidence_label(value: float) -> str:
    if value >= 0.8:
        return "Alta"
    if value >= 0.5:
        return "Media"
    return "Baja"


def _render_aggregate_table(entity: str, kind: str, rows: list[dict]) -> str:
    """Render aggregate rows as a clean Markdown table.

    Replaces the legacy ``"Presupuesto X - cliente - - 1234.56 - estado -"``
    string formatting with structured columns. The table is the same
    shape the LLM and the grounded fallback will both see, so the user
    gets a readable answer whether the model succeeds or falls back.
    """
    if not rows:
        return ""

    # Pick the columns based on what the row carries.
    sample = rows[0]

    def _cell(value: Any) -> str:
        if value is None:
            return "-"
        text = str(value).strip()
        return text if text else "-"

    # Detect kind="top" rows (label = human description, value = amount)
    if kind == "top" and "label" in sample and "value" in sample:
        # Try to extract structured fields from the label by splitting on " - "
        headers = ["#", "Documento", "Cliente/Proveedor", "Importe", "Estado"]
        out_lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for idx, r in enumerate(rows, start=1):
            label = _cell(r.get("label"))
            value = _cell(r.get("value"))
            # Best-effort: split label by " - " to tease apart fields.
            # Label shape: "Presupuesto 260039 - cliente ACME - 8864.80 EUR - estado aceptado"
            # but missing values stay as bare "cliente", "estado", etc.
            doc_id = "-"
            party = "-"
            amount = "-"
            status = "-"
            extra = []
            for raw_part in label.split(" - "):
                part = raw_part.strip()
                if not part:
                    continue
                # Strip leading " -" dashes that landed here when the
                # upstream label had empty fields back-to-back
                # (e.g. "cliente - - 8864.80").
                while part.startswith("-"):
                    part = part.lstrip("- ").strip()
                    if not part:
                        break
                if not part or part == "-":
                    continue
                low = part.lower()
                # Field with empty value: bare "cliente", "estado", "proveedor"
                if low in {"cliente", "proveedor", "estado"}:
                    continue
                # Field prefix with empty value, e.g. "cliente - " (already filtered above
                # because the post-split " - " lands as a "-")
                if low.startswith("cliente ") or low.startswith("proveedor ") or low.startswith("estado "):
                    value_after = part.split(" ", 1)[1].strip()
                    if value_after and value_after != "-":
                        if low.startswith("cliente ") or low.startswith("proveedor "):
                            party = value_after
                        elif low.startswith("estado "):
                            status = value_after
                    continue
                if low.startswith("presupuesto ") or low.startswith("pedido ") or low.startswith("factura "):
                    doc_id = part
                    continue
                # Heuristic: amount-like (contains digits and '.' or ',')
                if any(ch.isdigit() for ch in part) and ("." in part or "," in part):
                    amount = part
                    continue
                extra.append(part)
            if value not in {"-", ""} and amount == "-":
                amount = value
            if extra and party == "-":
                party = " / ".join(extra)
            out_lines.append(
                f"| {idx} | {doc_id} | {party} | {amount} | {status} |"
            )
        return "\n".join(out_lines)

    # Generic rows: key | value (and optional count)
    if "label" in sample or "metric" in sample:
        headers = ["#", "Etiqueta", "Valor"]
        if any("count" in (r or {}) for r in rows):
            headers.append("Docs")
        out_lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for idx, r in enumerate(rows, start=1):
            label = _cell(r.get("label") or r.get("metric"))
            value = _cell(r.get("value"))
            row = f"| {idx} | {label} | {value} |"
            if "Docs" in headers:
                cnt = _cell(r.get("count"))
                row += f" {cnt} |"
            out_lines.append(row)
        return "\n".join(out_lines)

    # Last resort: serialise rows as JSON lines
    return "\n".join(f"- `{json.dumps(r, ensure_ascii=False)}`" for r in rows)
