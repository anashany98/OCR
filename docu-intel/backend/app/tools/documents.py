"""Document lookup, details, and relationship tools.

Used by the AI agent to understand files and connect them to the
rest of the project, instead of just returning text snippets.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    BudgetLine,
    Document,
    DocumentBlock,
    DocumentEntity,
    DocumentPage,
    Invoice,
    Order,
    OrderLine,
    Plan,
    PlanDimension,
    PlanRoom,
)
from app.services.search_service import search_text

logger = logging.getLogger(__name__)


def search_documents(db: Session, query: str, document_type: str | None = None, limit: int = 10):
    results = search_text(db, query, limit=limit)
    if document_type:
        results = [item for item in results if item.document_type == document_type]
    return results[:limit]


def get_document(db: Session, document_id: int):
    return db.get(Document, document_id)


def get_document_blocks(db: Session, document_id: int, page_number: int | None = None):
    stmt = select(DocumentBlock).where(DocumentBlock.document_id == document_id)
    if page_number:
        stmt = stmt.where(DocumentBlock.page_number == page_number)
    return list(db.scalars(stmt.limit(200)).all())


def find_document_by_filename(db: Session, query: str, limit: int = 5) -> list[Document]:
    """Partial / case-insensitive match on `original_filename`. The most-recent
    match wins, ties broken by relevance score when available."""
    pattern = f"%{query.strip()}%"
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(Document.original_filename.ilike(pattern))
    )
    return list(db.scalars(stmt.order_by(Document.id.desc()).limit(limit)).all())


def get_document_full_details(db: Session, document_id: int) -> dict | None:
    """Return the document plus every extracted entity (budget, order, invoice,
    plan, rooms, dimensions, line items) as a single structured dict. The
    agent uses this to ground the LLM with facts instead of raw text."""
    document = db.get(Document, document_id)
    if not document:
        return None

    # Image documents: include a vision description in the snapshot so
    # the frontend can show "Visión aplicada" and the LLM can use the
    # actual visual content (not just bad OCR). Best-effort: failure to
    # reach the vision model is non-fatal.
    details: dict = {
        "id": document.id,
        "filename": document.original_filename,
        "source_path": document.source_path,
        "document_type": document.document_type,
        "status": document.status,
        "quality_status": document.quality_status,
        "confidence": document.confidence,
        "page_count": document.page_count,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "processed_at": document.processed_at.isoformat() if document.processed_at else None,
        "error_message": document.error_message,
        "entities": {},
    }
    _maybe_attach_vision_description(details, document)
    _attach_entity_payload(details, document, db)
    _maybe_attach_markdown_table_entities(details, document, db)
    return details


def _attach_entity_payload(details: dict, document: Document, db: Session) -> None:
    """Attach the budget/order/invoice/plan/generic entities to details.
    Pulled out of get_document_full_details so it can be reused from the
    streaming endpoint."""
    document_id = document.id
    entities = details["entities"]

    budget = db.scalar(select(Budget).where(Budget.document_id == document_id).limit(1))
    if budget:
        lines = list(
            db.scalars(
                select(BudgetLine)
                .where(BudgetLine.budget_id == budget.id)
                .order_by(BudgetLine.id.asc())
            ).all()
        )
        entities["budget"] = {
            "number": budget.budget_number,
            "client": budget.client_name,
            "date": budget.date.isoformat() if budget.date else None,
            "total_amount": budget.total_amount,
            "currency": budget.currency,
            "status": budget.status,
            "accepted": budget.accepted_detected,
            "confidence": budget.confidence,
            "line_count": len(lines),
            "lines_preview": [
                {
                    "reference": ln.reference,
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "unit": ln.unit,
                    "unit_price": ln.unit_price,
                    "total_price": ln.total_price,
                }
                for ln in lines[:8]
            ],
        }

    order = db.scalar(select(Order).where(Order.document_id == document_id).limit(1))
    if order:
        lines = list(
            db.scalars(
                select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id.asc())
            ).all()
        )
        entities["order"] = {
            "number": order.order_number,
            "supplier": order.supplier_name,
            "client": order.client_name,
            "date": order.date.isoformat() if order.date else None,
            "total_amount": order.total_amount,
            "currency": order.currency,
            "related_budget_id": order.related_budget_id,
            "confidence": order.confidence,
            "line_count": len(lines),
            "lines_preview": [
                {
                    "reference": ln.reference,
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "total_price": ln.total_price,
                }
                for ln in lines[:8]
            ],
        }

    invoice = db.scalar(select(Invoice).where(Invoice.document_id == document_id).limit(1))
    if invoice:
        entities["invoice"] = {
            "number": invoice.invoice_number,
            "supplier": invoice.supplier_name,
            "client": invoice.client_name,
            "date": invoice.date.isoformat() if invoice.date else None,
            "total_amount": invoice.total_amount,
            "currency": invoice.currency,
            "related_order_id": invoice.related_order_id,
            "confidence": invoice.confidence,
        }

    plan = db.scalar(select(Plan).where(Plan.document_id == document_id).limit(1))
    if plan:
        rooms = list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan.id)).all())
        dimensions = list(
            db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan.id)).all()
        )
        entities["plan"] = {
            "project_name": plan.project_name,
            "scale_text": plan.scale_text,
            "scale_ratio": plan.scale_ratio,
            "unit": plan.unit,
            "has_valid_scale": plan.has_valid_scale,
            "confidence": plan.scale_confidence,
            "room_count": len(rooms),
            "rooms_preview": [
                {
                    "name": r.name,
                    "area_m2": r.area_m2,
                    "width_m": r.width_m,
                    "length_m": r.length_m,
                    "needs_review": r.needs_review,
                }
                for r in rooms[:10]
            ],
            "dimension_count": len(dimensions),
        }

    ents = list(
        db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.document_id == document_id)
            .order_by(DocumentEntity.confidence.desc().nullslast())
            .limit(20)
        ).all()
    )
    if ents:
        entities["generic"] = [
            {
                "type": e.entity_type,
                "value": e.entity_value,
                "page": e.page_number,
                "confidence": e.confidence,
            }
            for e in ents
        ]


def _maybe_attach_vision_description(details: dict, document: Document) -> None:
    """If the document is an image, ask the configured vision model for a
    description and attach it to `details['vision']`. Best-effort: any
    failure (no model configured, file missing, request fails) is
    silently dropped so the rest of the snapshot still works."""
    from app.core.config import settings

    logger = logging.getLogger("app.tools.documents")
    filename = (details.get("filename") or "").lower()
    if not any(
        filename.endswith(ext)
        for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
    ):
        return
    if not (settings.vision_base_url and settings.vision_model):
        return
    if not document.stored_filename:
        return
    # Resolve the absolute path to the file on disk.
    from pathlib import Path

    files_dir = Path(settings.files_dir)
    candidate = files_dir / document.stored_filename
    if not candidate.exists():
        # Try source_path as a last resort.
        if document.source_path:
            candidate = Path(document.source_path)
        if not candidate.exists():
            return
    try:
        from app.ai.local_client import LocalVisionClient
        from app.services.vision_manager import VisionManager

        # On-demand vision: load the model only when we actually need
        # it. If the load fails (no lms shim reachable, etc.) we still
        # try the API call — LM Studio might already have the model
        # resident, in which case it works without a load step.
        VisionManager.cancel_pending_unload()
        if not VisionManager.is_loaded():
            loaded = VisionManager.ensure_loaded()
            if not loaded:
                logger.debug(
                    "VisionManager.ensure_loaded returned False; "
                    "vision call may still work if the model is resident"
                )

        client = LocalVisionClient()
        # The vision call is async, but this helper is called from a sync
        # code path (which is itself called from inside an async request
        # handler in the streaming endpoint). Using ``asyncio.run`` here
        # would crash because the request already has a running event
        # loop. Run the coroutine in a separate worker thread instead so
        # the vision call never blocks the rest of the pipeline.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run_vision_sync, client, candidate)
            description = future.result(timeout=settings.vision_timeout_seconds + 10)
        details["vision"] = {
            "model": settings.vision_model,
            "description": description,
            "applied_at": datetime.now(timezone.utc).isoformat() + "Z",
        }
        # Schedule a delayed unload so the GPU memory is released
        # when no more image work is pending.
        VisionManager.schedule_unload()
    except Exception:
        # Vision is best-effort; never break the rest of the pipeline.
        logger.debug("vision_description_failed document_id=%s", document.id, exc_info=True)
        return


def _run_vision_sync(client, candidate):
    """Run the async vision describe in a fresh event loop. Used by
    ``_maybe_attach_vision_description`` which lives on the sync path."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(client.describe(candidate))
    finally:
        loop.close()


def _maybe_attach_markdown_table_entities(details: dict, document: Document, db: Session) -> None:
    """For Excel / scanned-PDF-via-vision / text-extracted PDFs, the page
    text is a markdown table. This pulls line items (description,
    quantity, unit price, total) out of that table and merges them into
    the document entities so the LLM and the frontend can render real
    line items even when the structured tables are empty."""
    try:
        from app.services.markdown_entities import (
            extract_all_line_items,
            find_total_amount,
        )

        pages = list(
            db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == document.id)
                .order_by(DocumentPage.page_number.asc())
            ).all()
        )
        if not pages:
            return
        combined_text = "\n\n".join(p.text or "" for p in pages)
        if "|" not in combined_text:
            return
        items = extract_all_line_items(combined_text)
        if not items:
            return
        details.setdefault("entities", {}).setdefault("table_lines", items)
        # If we found a TOTAL row and the budget/invoice total is missing,
        # patch it in so the LLM has the real number.
        total_value, total_label = find_total_amount(combined_text)
        if total_value is not None:
            budget = details["entities"].get("budget")
            invoice = details["entities"].get("invoice")
            if budget and budget.get("total_amount") is None:
                budget["total_amount"] = total_value
                budget["total_source"] = "markdown_table"
                if total_label:
                    budget.setdefault("notes", []).append(f"TOTAL extraido de tabla: {total_label}")
            elif invoice and invoice.get("total_amount") is None:
                invoice["total_amount"] = total_value
                invoice["total_source"] = "markdown_table"
    except Exception:
        # Markdown extraction is best-effort; never break the rest of the pipeline.
        logger.debug("markdown_table_extraction_failed document_id=%s", document.id, exc_info=True)
        return


def get_related_documents(db: Session, document_id: int, hops: int = 1) -> list[dict]:
    """Return related documents with a human-readable label explaining WHY each
    one is related, walking the document graph up to `hops` levels deep.

    With hops=1 (default) you get the immediate neighborhood of the document.
    With hops=2 the tool also recurses into every related document and pulls
    ITS relations, so the LLM receives a wider slice of the project.

    Connections considered per hop:
    - presupuesto -> pedido (and back)
    - pedido -> factura (and back)
    - presupuesto -> factura (via pedido)
    - documents with the same supplier (across orders)
    - documents with the same client (across budgets)
    - documents in the same source folder

    Deduplicated by document id, and the strongest relation wins ties.
    Capped so the LLM does not get flooded.
    """
    document = db.get(Document, document_id)
    if not document:
        return []

    related: dict[int, dict] = {}
    seen_frontier: set[int] = {document_id}

    def _add(doc: Document | None, relation: str, label: str, depth: int) -> None:
        if doc is None or doc.id == document_id or doc.deleted_at is not None:
            return
        # Stronger (lower-depth) relations win over weaker ones.
        existing = related.get(doc.id)
        if existing is None or existing["depth"] > depth:
            related[doc.id] = {
                "document": doc,
                "relation": relation,
                "label": label,
                "depth": depth,
            }

    def _expand(doc_id: int, depth: int) -> None:
        if depth > hops:
            return
        doc = db.get(Document, doc_id)
        if doc is None or doc.deleted_at is not None:
            return

        # ---- presupuesto <-> pedido ----
        budget = db.scalar(select(Budget).where(Budget.document_id == doc_id).limit(1))
        if budget:
            orders = db.scalars(select(Order).where(Order.related_budget_id == budget.id)).all()
            for order in orders:
                order_doc = db.get(Document, order.document_id) if order.document_id else None
                _add(
                    order_doc,
                    "presupuesto_to_pedido",
                    f"Pedido {order.order_number or order.id} generado a partir de este presupuesto",
                    depth,
                )
                # pedido -> factura
                invoices = db.scalars(
                    select(Invoice).where(Invoice.related_order_id == order.id)
                ).all()
                for inv in invoices:
                    inv_doc = db.get(Document, inv.document_id) if inv.document_id else None
                    _add(
                        inv_doc,
                        "pedido_to_factura",
                        f"Factura {inv.invoice_number or inv.id} que paga el pedido {order.order_number or order.id}",
                        depth,
                    )
                # budget -> other budgets same client
                if budget.client_name and depth == 1:
                    siblings = db.scalars(
                        select(Budget)
                        .where(Budget.client_name == budget.client_name)
                        .where(Budget.document_id != doc_id)
                        .order_by(Budget.id.desc())
                        .limit(4)
                    ).all()
                    for sib in siblings:
                        sib_doc = db.get(Document, sib.document_id) if sib.document_id else None
                        _add(
                            sib_doc,
                            "same_client",
                            f"Otro presupuesto del mismo cliente ({budget.client_name})",
                            depth,
                        )

        # ---- pedido -> presupuesto / factura / same supplier ----
        order = db.scalar(select(Order).where(Order.document_id == doc_id).limit(1))
        if order:
            if order.related_budget_id:
                related_budget = db.get(Budget, order.related_budget_id)
                if related_budget:
                    budget_doc = (
                        db.get(Document, related_budget.document_id)
                        if related_budget.document_id
                        else None
                    )
                    _add(
                        budget_doc,
                        "pedido_to_presupuesto",
                        f"Presupuesto {related_budget.budget_number or related_budget.id} del que deriva este pedido",
                        depth,
                    )
            invoices = db.scalars(select(Invoice).where(Invoice.related_order_id == order.id)).all()
            for inv in invoices:
                inv_doc = db.get(Document, inv.document_id) if inv.document_id else None
                _add(
                    inv_doc,
                    "pedido_to_factura",
                    f"Factura {inv.invoice_number or inv.id} que paga este pedido",
                    depth,
                )
            if order.supplier_name and depth == 1:
                siblings = db.scalars(
                    select(Order)
                    .where(Order.supplier_name == order.supplier_name)
                    .where(Order.document_id != doc_id)
                    .order_by(Order.id.desc())
                    .limit(4)
                ).all()
                for sib in siblings:
                    sib_doc = db.get(Document, sib.document_id) if sib.document_id else None
                    _add(
                        sib_doc,
                        "same_supplier",
                        f"Otro pedido del mismo proveedor ({order.supplier_name})",
                        depth,
                    )

        # ---- factura -> pedido -> presupuesto ----
        invoice = db.scalar(select(Invoice).where(Invoice.document_id == doc_id).limit(1))
        if invoice:
            if invoice.related_order_id:
                related_order = db.get(Order, invoice.related_order_id)
                if related_order:
                    order_doc = (
                        db.get(Document, related_order.document_id)
                        if related_order.document_id
                        else None
                    )
                    _add(
                        order_doc,
                        "factura_to_pedido",
                        f"Pedido {related_order.order_number or related_order.id} que origina esta factura",
                        depth,
                    )
                    if related_order.related_budget_id:
                        related_budget = db.get(Budget, related_order.related_budget_id)
                        if related_budget:
                            budget_doc = (
                                db.get(Document, related_budget.document_id)
                                if related_budget.document_id
                                else None
                            )
                            _add(
                                budget_doc,
                                "factura_to_presupuesto",
                                f"Presupuesto {related_budget.budget_number or related_budget.id} en el origen de esta factura",
                                depth,
                            )

        # ---- plan -> related plans same project ----
        plan = db.scalar(select(Plan).where(Plan.document_id == doc_id).limit(1))
        if plan and plan.project_name and depth == 1:
            siblings = db.scalars(
                select(Plan)
                .where(Plan.project_name == plan.project_name)
                .where(Plan.document_id != doc_id)
                .order_by(Plan.id.desc())
                .limit(4)
            ).all()
            for sib in siblings:
                sib_doc = db.get(Document, sib.document_id) if sib.document_id else None
                _add(
                    sib_doc,
                    "same_project",
                    f"Otro plano del mismo proyecto ({plan.project_name})",
                    depth,
                )

        # ---- same source folder ----
        if doc.source_path and depth == 1:
            path_prefix = doc.source_path.rsplit("/", 1)[0] + "/"
            siblings = db.scalars(
                select(Document)
                .where(Document.id != doc_id)
                .where(Document.deleted_at.is_(None))
                .where(Document.source_path.like(path_prefix + "%"))
                .order_by(Document.id.desc())
                .limit(6)
            ).all()
            for sib in siblings:
                _add(sib, "same_folder", f"En la misma carpeta ({path_prefix})", depth)

    # Walk the graph up to `hops` levels.
    frontier: list[tuple[int, int]] = [(document_id, 0)]
    while frontier:
        next_frontier: list[tuple[int, int]] = []
        for doc_id, depth in frontier:
            if doc_id in seen_frontier and depth > 0:
                continue
            seen_frontier.add(doc_id)
            pre = len(related)
            _expand(doc_id, depth + 1)
            if depth + 1 < hops:
                for entry in list(related.values())[pre:]:
                    next_frontier.append((entry["document"].id, depth + 1))
        frontier = next_frontier

    # Strip the internal `depth` field before returning; frontend doesn't need it.
    result = []
    for entry in related.values():
        result.append(
            {
                "document": entry["document"],
                "relation": entry["relation"],
                "label": entry["label"],
            }
        )
    return result[:16]


def get_duplicate_documents(db: Session):
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "duplicate")
            .order_by(Document.id.desc())
            .limit(50)
        ).all()
    )


def get_ocr_review_documents(db: Session):
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(
                (Document.status == "failed")
                | (Document.status == "needs_review")
                | (Document.confidence < 0.75)
            )
            .order_by(Document.id.desc())
            .limit(50)
        ).all()
    )
