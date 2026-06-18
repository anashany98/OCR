from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (  # noqa: E402  (intentional — logger depends on this module)
    Budget,
    BudgetLine,
    Document,
    DocumentBlock,
    DocumentChunk,
    DocumentEntity,
    Invoice,
    Order,
    OrderLine,
    Plan,
    PlanDimension,
    PlanRoom,
)
from app.services.tenant_access import AccessScope, filter_records_by_document_scope
from app.services.search_service import search_hybrid as run_hybrid_search
from app.services.search_service import search_text


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


def search_budgets(db: Session, query: str, status: str | None = None):
    pattern = f"%{query}%"
    stmt = select(Budget).where(
        (Budget.budget_number.ilike(pattern)) | (Budget.client_name.ilike(pattern))
    )
    if status:
        stmt = stmt.where(Budget.status == status)
    return list(db.scalars(stmt.limit(20)).all())


def get_budget_by_number(db: Session, budget_number: str):
    return db.scalar(select(Budget).where(Budget.budget_number == budget_number).limit(1))


def get_accepted_budgets_without_order(db: Session):
    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    return list(
        db.scalars(
            select(Budget)
            .where(Budget.accepted_detected.is_(True))
            .where(Budget.id.not_in(ordered_budget_ids))
            .limit(50)
        ).all()
    )


def search_orders(db: Session, query: str):
    pattern = f"%{query}%"
    stmt = select(Order).where(
        (Order.order_number.ilike(pattern)) | (Order.supplier_name.ilike(pattern))
    )
    return list(db.scalars(stmt.limit(20)).all())


def get_order_by_number(db: Session, order_number: str):
    return db.scalar(select(Order).where(Order.order_number == order_number).limit(1))


# ---------------------------------------------------------------------------
# CTX-6 — Structured business tools (SQL-first).
#
# Each function returns a small dataclass-like ``dict`` so the
# orchestrator can decide whether the answer is grounded (a real
# number was found) or has to fall back to RAG. The dicts are also
# serialised into the AIAnswer ``resolved_document_json`` snapshot so
# the admin UI can render the structured answer without an extra
# request.
# ---------------------------------------------------------------------------


def _budget_by_number_or_id(db: Session, budget_number: str | None, budget_id: int | None) -> Budget | None:
    """Resolve a :class:`Budget` by number or by id, whichever is set.

    Returns ``None`` when neither is provided or when no row matches.
    Falls back to the pre-normalised column (``budget_number_normalized``)
    when the exact match fails so a search for ``"260009"`` still finds
    a budget stored as ``" 260 009 "``.
    """
    import unicodedata

    if budget_id is not None:
        return db.get(Budget, int(budget_id))
    if not budget_number:
        return None
    budget = db.scalar(
        select(Budget).where(Budget.budget_number == budget_number).limit(1)
    )
    if budget is not None:
        return budget
    # Fallback: normalised lookup (whitespace / hyphen insensitive).
    raw = unicodedata.normalize("NFKD", budget_number)
    raw = raw.encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[\s\-_/.,]", "", raw).lower()
    if not norm:
        return None
    return db.scalar(
        select(Budget).where(Budget.budget_number_normalized == norm).limit(1)
    )


def get_budget_total(
    db: Session,
    *,
    budget_number: str | None = None,
    budget_id: int | None = None,
) -> dict:
    """Return a small dict with the budget's total + the line evidence.

    Response shape::

        {
            "found": True/False,
            "budget_number": "260009",
            "document_id": 123,
            "total_amount": 1234.5,
            "currency": "EUR",
            "line_count": 4,
            "lines_total": 1234.5,  # sum of line totals when available
            "lines_match_total": True/False,  # do the lines add up to the total?
            "status": "aceptado",
            "accepted": True/False,
            "confidence": 0.9,
            "client_name": "ALEJANDRA ...",
        }

    The orchestrator uses ``found`` + ``confidence`` to decide
    whether the answer is grounded or has to fall back to RAG.
    """
    budget = _budget_by_number_or_id(db, budget_number, budget_id)
    if budget is None:
        return {
            "found": False,
            "budget_number": budget_number,
            "budget_id": budget_id,
            "reason": "presupuesto no encontrado",
        }
    lines = list(
        db.scalars(
            select(BudgetLine).where(BudgetLine.budget_id == budget.id).order_by(BudgetLine.id.asc())
        ).all()
    )
    lines_total = 0.0
    for ln in lines:
        if ln.total_price is not None:
            lines_total += float(ln.total_price)
    match = (
        budget.total_amount is not None
        and lines
        and abs(lines_total - float(budget.total_amount)) <= max(1.0, float(budget.total_amount) * 0.01)
    )
    return {
        "found": True,
        "budget_number": budget.budget_number,
        "budget_id": budget.id,
        "document_id": budget.document_id,
        "client_name": budget.client_name,
        "total_amount": budget.total_amount,
        "currency": budget.currency,
        "status": budget.status,
        "accepted": bool(budget.accepted_detected),
        "confidence": budget.confidence,
        "line_count": len(lines),
        "lines_total": round(lines_total, 2) if lines else None,
        "lines_match_total": bool(match) if lines else None,
    }


def get_budget_lines(
    db: Session,
    *,
    budget_number: str | None = None,
    budget_id: int | None = None,
    limit: int = 25,
) -> dict:
    """Return the budget's line items as a list of small dicts.

    Empty list when the budget does not exist or has no lines. The
    shape mirrors what the LLM needs: ``reference``, ``description``,
    ``quantity``, ``unit``, ``unit_price``, ``total_price`` and the
    line-level ``confidence``.
    """
    budget = _budget_by_number_or_id(db, budget_number, budget_id)
    if budget is None:
        return {
            "found": False,
            "budget_number": budget_number,
            "budget_id": budget_id,
            "lines": [],
        }
    lines = list(
        db.scalars(
            select(BudgetLine)
            .where(BudgetLine.budget_id == budget.id)
            .order_by(BudgetLine.id.asc())
            .limit(limit)
        ).all()
    )
    return {
        "found": True,
        "budget_number": budget.budget_number,
        "budget_id": budget.id,
        "client_name": budget.client_name,
        "total_amount": budget.total_amount,
        "currency": budget.currency,
        "lines": [
            {
                "reference": ln.reference,
                "description": (ln.description or "").strip(),
                "quantity": ln.quantity,
                "unit": ln.unit,
                "unit_price": ln.unit_price,
                "total_price": ln.total_price,
                "confidence": ln.confidence,
            }
            for ln in lines
        ],
    }


def get_invoiced_amount_for_budget(
    db: Session,
    *,
    budget_number: str | None = None,
    budget_id: int | None = None,
) -> dict:
    """Sum the invoice totals for the orders linked to a budget.

    The path is ``Budget → related Orders → related Invoices → total``.
    Budgets with no orders or no invoices return ``invoiced=0`` so the
    user gets an honest "todavia no se ha facturado nada" answer
    instead of a hallucinated amount.
    """
    budget = _budget_by_number_or_id(db, budget_number, budget_id)
    if budget is None:
        return {
            "found": False,
            "budget_number": budget_number,
            "budget_id": budget_id,
            "invoiced": 0.0,
            "invoice_count": 0,
        }
    order_ids = list(
        db.scalars(select(Order.id).where(Order.related_budget_id == budget.id)).all()
    )
    if not order_ids:
        return {
            "found": True,
            "budget_number": budget.budget_number,
            "budget_id": budget.id,
            "order_count": 0,
            "invoiced": 0.0,
            "invoice_count": 0,
            "orders": [],
        }
    invoices = list(
        db.scalars(select(Invoice).where(Invoice.related_order_id.in_(order_ids))).all()
    )
    invoiced = sum(float(inv.total_amount or 0.0) for inv in invoices)
    return {
        "found": True,
        "budget_number": budget.budget_number,
        "budget_id": budget.id,
        "order_count": len(order_ids),
        "invoice_count": len(invoices),
        "invoiced": round(invoiced, 2),
        "orders": [
            {"order_id": oid, "invoiced": False} for oid in order_ids
        ],
        "invoices": [
            {
                "invoice_number": inv.invoice_number,
                "total_amount": inv.total_amount,
                "currency": inv.currency,
                "date": inv.date.isoformat() if inv.date else None,
            }
            for inv in invoices
        ],
    }


def list_recent_accepted_budgets(db: Session, limit: int = 10) -> dict:
    """Recent accepted budgets, newest first.

    Used by the ``accepted_budgets`` intent ("últimos presupuestos
    aceptados"). Excludes duplicates / failed documents so the
    result is a clean list the user can pick from.
    """
    budgets = list(
        db.scalars(
            select(Budget)
            .where(Budget.accepted_detected.is_(True))
            .order_by(Budget.created_at.desc())
            .limit(limit)
        ).all()
    )
    return {
        "found": bool(budgets),
        "count": len(budgets),
        "budgets": [
            {
                "budget_number": b.budget_number,
                "client_name": b.client_name,
                "total_amount": b.total_amount,
                "currency": b.currency,
                "date": b.date.isoformat() if b.date else None,
                "status": b.status,
                "document_id": b.document_id,
                "confidence": b.confidence,
            }
            for b in budgets
        ],
    }


def get_invoice_origin_order(
    db: Session,
    *,
    invoice_number: str | None = None,
    invoice_id: int | None = None,
) -> dict:
    """Find the order that originated an invoice.

    Returns the order + the budget it traces back to (when known) so
    the assistant can answer "esta factura viene del pedido X que
    deriva del presupuesto Y" in one shot.
    """
    if invoice_id is not None:
        invoice = db.get(Invoice, int(invoice_id))
    elif invoice_number:
        invoice = db.scalar(
            select(Invoice).where(Invoice.invoice_number == invoice_number).limit(1)
        )
    else:
        invoice = None
    if invoice is None:
        return {"found": False, "invoice_number": invoice_number, "invoice_id": invoice_id}
    order = (
        db.get(Order, invoice.related_order_id) if invoice.related_order_id else None
    )
    budget = (
        db.get(Budget, order.related_budget_id)
        if order is not None and order.related_budget_id
        else None
    )
    return {
        "found": True,
        "invoice_number": invoice.invoice_number,
        "invoice_id": invoice.id,
        "document_id": invoice.document_id,
        "total_amount": invoice.total_amount,
        "currency": invoice.currency,
        "date": invoice.date.isoformat() if invoice.date else None,
        "order": (
            {
                "order_number": order.order_number,
                "order_id": order.id,
                "supplier_name": order.supplier_name,
                "total_amount": order.total_amount,
            }
            if order
            else None
        ),
        "budget": (
            {
                "budget_number": budget.budget_number,
                "budget_id": budget.id,
                "client_name": budget.client_name,
            }
            if budget
            else None
        ),
    }


def find_delivery_note_in_scope(
    db: Session,
    *,
    budget_number: str | None = None,
    folder_path: str | None = None,
    source_path_like: str | None = None,
) -> dict:
    """Search for a delivery note (albaran) inside the active scope.

    The search is by document_type (albaran / delivery_note) and by
    filename pattern (the words ``albaran``, ``albaran``, ``entrega``).
    The scope filter is mandatory: when no budget / folder hint is
    given, the function returns an empty list (refusing to look
    outside an active scope) so a follow-up like "dispones del albaran
    de entrega" can never silently jump to a different budget.

    The shape mirrors what the orchestrator needs::

        {
            "found": bool,
            "matches": [{"document_id", "filename", "source_path",
                         "page_number", "confidence", "score"}],
            "scope": "...",
        }
    """
    pattern = "%albaran%"
    candidates: list[Document] = []
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if source_path_like:
        stmt = stmt.where(Document.source_path.ilike(source_path_like))
    elif folder_path:
        stmt = stmt.where(Document.source_path.ilike(f"%{folder_path}%"))
    elif budget_number:
        stmt = stmt.where(Document.source_path.ilike(f"%Presupuesto {budget_number}%"))
    else:
        # No scope: refuse to guess.
        return {
            "found": False,
            "matches": [],
            "scope": None,
            "reason": "no se ha indicado ambito (presupuesto o carpeta)",
        }
    candidates = list(
        db.scalars(
            stmt.where(
                (Document.document_type.in_(["albaran", "delivery_note"]))
                | (Document.original_filename.ilike(pattern))
            )
            .order_by(Document.id.desc())
            .limit(10)
        ).all()
    )
    return {
        "found": bool(candidates),
        "scope": (
            f"Presupuesto {budget_number}"
            if budget_number
            else folder_path
            or source_path_like
        ),
        "matches": [
            {
                "document_id": d.id,
                "filename": d.original_filename,
                "source_path": d.source_path,
                "document_type": d.document_type,
                "status": d.status,
                "confidence": d.confidence,
            }
            for d in candidates
        ],
    }


# Keywords that signal a shipping/transport cost. Kept in a module
# constant so tests can assert against it without importing the
# tools module.
SHIPPING_KEYWORDS: tuple[str, ...] = (
    "envio",
    "envio",
    "transporte",
    "portes",
    "flete",
    "fletes",
    "freight",
    "shipping",
    "logistica",
    "entrega",
)


def find_shipping_cost_in_scope(
    db: Session,
    *,
    budget_number: str | None = None,
    folder_path: str | None = None,
    source_path_like: str | None = None,
    limit: int = 5,
) -> dict:
    """Find the shipping cost inside the active scope.

    The search is restricted to documents in the scope and looks for
    the SHIPPING_KEYWORDS in chunk text + line descriptions. Returns
    a list of small dicts with the candidate amount, the document it
    came from, and the keyword that matched so the LLM can cite the
    evidence and the user can verify it.
    """
    if not (budget_number or folder_path or source_path_like):
        return {
            "found": False,
            "candidates": [],
            "scope": None,
            "reason": "no se ha indicado ambito (presupuesto o carpeta)",
        }
    like = (
        source_path_like
        or (f"%{folder_path}%" if folder_path else None)
        or f"%Presupuesto {budget_number}%"
    )
    # ILIKE any of the shipping keywords against chunk_text.
    keyword_ors = [
        DocumentChunk.chunk_text.ilike(f"%{kw}%") for kw in SHIPPING_KEYWORDS
    ]
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.deleted_at.is_(None))
        .where(Document.source_path.ilike(like))
        .where(or_(*keyword_ors))
        .order_by(DocumentChunk.confidence.desc().nullslast())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    candidates: list[dict] = []
    for chunk, doc in rows:
        if not chunk.chunk_text:
            continue
        candidates.append(
            {
                "document_id": doc.id,
                "filename": doc.original_filename,
                "source_path": doc.source_path,
                "page_number": chunk.page_number,
                "excerpt": (chunk.chunk_text or "")[:240],
                "chunk_confidence": chunk.confidence,
                "document_confidence": doc.confidence,
            }
        )
    return {
        "found": bool(candidates),
        "scope": (
            f"Presupuesto {budget_number}"
            if budget_number
            else folder_path
            or source_path_like
        ),
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Document lookup and relationship tools (used by the AI agent to actually
# *understand* a file and connect it to the rest of the project, instead of
# just returning a list of text snippets).
# ---------------------------------------------------------------------------


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

    logger = logging.getLogger("app.tools.internal")
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
            "applied_at": datetime.utcnow().isoformat() + "Z",
        }
        # Schedule a delayed unload so the GPU memory is released
        # when no more image work is pending.
        VisionManager.schedule_unload()
    except Exception:
        # Vision is best-effort; never break the rest of the pipeline.
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
        from app.models import DocumentPage
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


def search_plans(db: Session, query: str):
    return list(
        db.scalars(select(Plan).where(Plan.project_name.ilike(f"%{query}%")).limit(20)).all()
    )


def get_plan_rooms(db: Session, plan_id: int):
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


def get_plan_dimensions(db: Session, plan_id: int):
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


def get_room_measurements(db: Session, plan_id: int, room_name: str):
    pattern = f"%{room_name}%"
    return list(
        db.scalars(
            select(PlanRoom).where(PlanRoom.plan_id == plan_id).where(PlanRoom.name.ilike(pattern))
        ).all()
    )


def search_plan_room_measurements(db: Session, room_name: str):
    pattern = f"%{room_name}%"
    return list(
        db.execute(
            select(Plan, PlanRoom, Document)
            .join(PlanRoom, PlanRoom.plan_id == Plan.id)
            .join(Document, Document.id == Plan.document_id)
            .where(PlanRoom.name.ilike(pattern))
            .where(Document.deleted_at.is_(None))
            .order_by(PlanRoom.needs_review.asc(), Plan.created_at.desc())
            .limit(20)
        ).all()
    )


def search_entities(db: Session, entity_type: str, value: str):
    return list(
        db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.entity_value.ilike(f"%{value}%"))
            .limit(50)
        ).all()
    )


def hybrid_search(db: Session, query: str, filters: dict | None = None):
    return run_hybrid_search(
        db, query, filters=(filters or {}), limit=(filters or {}).get("limit", 10)
    )


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


# ---------------------------------------------------------------------------
# Aggregate / analytics tools (used by the AI agent to answer questions
# like "cuanto nos hemos gastado en X" or "cuantos pedidos hay sin factura").
# ---------------------------------------------------------------------------


def _money_filters(kind: str, query: str) -> dict[str, Any]:
    """Pull a number, supplier/client/period hint out of a Spanish natural
    language query, so the aggregate queries can be filtered without the LLM
    having to translate its answer into SQL itself."""
    q = (query or "").lower()
    filters: dict[str, Any] = {}

    # Supplier / client name: look for "proveedor X", "del proveedor X",
    # "cliente X", "del cliente X". Take the rest of the sentence.
    m = re.search(
        r"(?:proveedor|proveedores)\s+(?:de\s+|del\s+|de la\s+)?([\wÀ-ſ &./'-]{2,60})",
        q,
    )
    if m:
        filters["supplier"] = m.group(1).strip(" .?!,;:")

    m = re.search(
        r"(?:cliente|clientes)\s+(?:de\s+|del\s+|de la\s+)?([\wÀ-ſ &./'-]{2,60})",
        q,
    )
    if m:
        filters["client"] = m.group(1).strip(" .?!,;:")

    # Numeric threshold: "mas de 10000", "que superan los 5000", "< 200",
    # "mayores a 1000".
    m = re.search(
        r"(?:mas de|mayores? a|superan?|por encima de|>)\s*(\d+(?:[.,]\d+)*)",
        q,
    )
    if m:
        filters["amount_min"] = float(m.group(1).replace(",", "."))
    m = re.search(
        r"(?:menos de|menores? a|por debajo de|<)\s*(\d+(?:[.,]\d+)*)",
        q,
    )
    if m:
        filters["amount_max"] = float(m.group(1).replace(",", "."))

    # Status / acceptance flags.
    if any(w in q for w in ["aceptad", "aprobad"]):
        filters["accepted"] = True
    if any(w in q for w in ["no aceptad", "rechazad", "pendiente de aceptar"]):
        filters["accepted"] = False
    if any(w in q for w in ["sin facturar", "sin factura", "no facturad"]):
        filters["invoiced"] = False
    if any(w in q for w in ["facturad", "con factura"]):
        filters["invoiced"] = True
    if any(w in q for w in ["sin pedido", "sin pedidos", "no tiene pedido"]):
        filters["has_order"] = False
    if any(w in q for w in ["con pedido"]):
        filters["has_order"] = True

    # Period / year: "este ano", "en 2024", "este mes".
    year_match = re.search(r"\b(20\d{2})\b", q)
    if year_match:
        filters["year"] = int(year_match.group(1))
    elif "este ano" in q or "este año" in q:
        filters["year"] = date.today().year
    elif "ano pasado" in q or "año pasado" in q:
        filters["year"] = date.today().year - 1
    elif "este mes" in q:
        filters["year"] = date.today().year
        filters["month"] = date.today().month

    return filters


def _budget_aggregate(
    db: Session,
    kind: str,
    filters: dict[str, Any],
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    """Build aggregate results for `kind` in {total, count, top, period}
    restricted to `Budget` records with the given filters."""
    stmt = select(Budget)
    if filters.get("supplier"):
        # Budgets don't link to suppliers directly; skip supplier filter.
        pass
    if filters.get("client"):
        stmt = stmt.where(Budget.client_name.ilike(f"%{filters['client']}%"))
    if filters.get("amount_min") is not None:
        stmt = stmt.where(Budget.total_amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        stmt = stmt.where(Budget.total_amount <= filters["amount_max"])
    if filters.get("accepted") is True:
        stmt = stmt.where(Budget.accepted_detected.is_(True))
    elif filters.get("accepted") is False:
        stmt = stmt.where(Budget.accepted_detected.is_(False))
    if filters.get("has_order") is False:
        ordered_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
        stmt = stmt.where(Budget.id.not_in(ordered_ids))

    budgets = list(db.scalars(stmt).all())
    if access_scope is not None:
        budgets = filter_records_by_document_scope(db, budgets, access_scope)

    if kind == "count":
        return [
            {
                "metric": "count",
                "value": len(budgets),
                "label": "presupuestos que cumplen los filtros",
            }
        ]
    if kind == "total":
        total = sum((b.total_amount or 0.0) for b in budgets if b.total_amount is not None)
        return [
            {
                "metric": "total_amount",
                "value": round(total, 2),
                "label": "suma de importes de presupuestos",
                "count": len(budgets),
            }
        ]
    if kind == "top":
        sorted_bs = sorted(budgets, key=lambda b: b.total_amount or 0, reverse=True)[:10]
        return [
            {
                "metric": "top_presupuesto",
                "value": b.total_amount,
                "label": (
                    f"Presupuesto {b.budget_number or b.id} - cliente {b.client_name or '-'} - "
                    f"{b.total_amount or 0:.2f} {b.currency or ''} - estado {b.status or '-'}"
                ).strip(),
                "document_id": b.document_id,
            }
            for b in sorted_bs
        ]
    return []


def _order_aggregate(
    db: Session,
    kind: str,
    filters: dict[str, Any],
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Order)
    if filters.get("supplier"):
        stmt = stmt.where(Order.supplier_name.ilike(f"%{filters['supplier']}%"))
    if filters.get("client"):
        stmt = stmt.where(Order.client_name.ilike(f"%{filters['client']}%"))
    if filters.get("amount_min") is not None:
        stmt = stmt.where(Order.total_amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        stmt = stmt.where(Order.total_amount <= filters["amount_max"])
    if filters.get("has_order") is True:
        stmt = stmt.where(Order.related_budget_id.is_not(None))
    elif filters.get("has_order") is False:
        stmt = stmt.where(Order.related_budget_id.is_(None))
    if filters.get("invoiced") is True:
        invoiced_ids = select(Invoice.related_order_id).where(Invoice.related_order_id.is_not(None))
        stmt = stmt.where(Order.id.in_(invoiced_ids))
    elif filters.get("invoiced") is False:
        invoiced_ids = select(Invoice.related_order_id).where(Invoice.related_order_id.is_not(None))
        stmt = stmt.where(Order.id.not_in(invoiced_ids))

    orders = list(db.scalars(stmt).all())
    if access_scope is not None:
        orders = filter_records_by_document_scope(db, orders, access_scope)

    if kind == "count":
        return [
            {"metric": "count", "value": len(orders), "label": "pedidos que cumplen los filtros"}
        ]
    if kind == "total":
        total = sum((o.total_amount or 0.0) for o in orders if o.total_amount is not None)
        return [
            {
                "metric": "total_amount",
                "value": round(total, 2),
                "label": "suma de importes de pedidos",
                "count": len(orders),
            }
        ]
    if kind == "top":
        sorted_os = sorted(orders, key=lambda o: o.total_amount or 0, reverse=True)[:10]
        return [
            {
                "metric": "top_pedido",
                "value": o.total_amount,
                "label": (
                    f"Pedido {o.order_number or o.id} - proveedor {o.supplier_name or '-'} - "
                    f"cliente {o.client_name or '-'} - {o.total_amount or 0:.2f} {o.currency or ''}"
                ).strip(),
                "document_id": o.document_id,
            }
            for o in sorted_os
        ]
    if kind == "by_supplier":
        groups: dict[str, dict[str, Any]] = {}
        for o in orders:
            key = o.supplier_name or "(sin proveedor)"
            g = groups.setdefault(key, {"label": key, "count": 0, "total": 0.0})
            g["count"] += 1
            if o.total_amount is not None:
                g["total"] += o.total_amount
        return [
            {
                "metric": "by_supplier",
                "value": round(g["total"], 2),
                "count": g["count"],
                "label": g["label"],
            }
            for g in sorted(groups.values(), key=lambda x: x["total"], reverse=True)[:10]
        ]
    return []


def _invoice_aggregate(
    db: Session,
    kind: str,
    filters: dict[str, Any],
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Invoice)
    if filters.get("supplier"):
        stmt = stmt.where(Invoice.supplier_name.ilike(f"%{filters['supplier']}%"))
    if filters.get("client"):
        stmt = stmt.where(Invoice.client_name.ilike(f"%{filters['client']}%"))
    if filters.get("amount_min") is not None:
        stmt = stmt.where(Invoice.total_amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        stmt = stmt.where(Invoice.total_amount <= filters["amount_max"])
    invoices = list(db.scalars(stmt).all())
    if access_scope is not None:
        invoices = filter_records_by_document_scope(db, invoices, access_scope)
    if kind == "count":
        return [
            {"metric": "count", "value": len(invoices), "label": "facturas que cumplen los filtros"}
        ]
    if kind == "total":
        total = sum((i.total_amount or 0.0) for i in invoices if i.total_amount is not None)
        return [
            {
                "metric": "total_amount",
                "value": round(total, 2),
                "label": "suma de importes facturados",
                "count": len(invoices),
            }
        ]
    return []


PRICE_AGGREGATE_KINDS = {"total", "top", "by_supplier", "period"}


def _filters_for_price_scope(
    filters: dict[str, Any], access_scope: AccessScope | None
) -> tuple[dict[str, Any], bool]:
    if access_scope is None or access_scope.can_view_prices:
        return filters, False
    clean = dict(filters)
    redacted = False
    for key in ("amount_min", "amount_max"):
        if key in clean:
            clean.pop(key, None)
            redacted = True
    return clean, redacted


def aggregate_business(
    db: Session,
    *,
    entity: str,
    kind: str,
    query: str | None = None,
    access_scope: AccessScope | None = None,
) -> dict[str, Any]:
    """Run an aggregate query against the structured business tables. Used
    by the agent to answer questions like "cuanto nos hemos gastado en X",
    "cuantos pedidos sin factura hay" or "cual es el proveedor top por
    importe". Returns a list of result rows plus the parsed filters so the
    LLM can show its work."""
    filters, price_redacted = _filters_for_price_scope(
        _money_filters(entity if not query else query, query or entity),
        access_scope,
    )
    if (
        access_scope is not None
        and not access_scope.can_view_prices
        and kind.lower() in PRICE_AGGREGATE_KINDS
    ):
        return {
            "entity": entity,
            "kind": kind,
            "rows": [],
            "filters": filters,
            "price_redacted": True,
            "warning": "Los importes estan ocultos por la politica de acceso del usuario.",
        }
    runner = {
        "budget": _budget_aggregate,
        "order": _order_aggregate,
        "invoice": _invoice_aggregate,
    }.get(entity.lower())
    if runner is None:
        return {
            "entity": entity,
            "kind": kind,
            "rows": [],
            "filters": filters,
            "error": f"Tipo de entidad no soportado: {entity}",
        }
    rows = runner(db, kind, filters, access_scope)
    return {
        "entity": entity,
        "kind": kind,
        "rows": rows,
        "filters": filters,
        "price_redacted": price_redacted,
    }
