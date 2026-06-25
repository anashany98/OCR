"""Budget-related tools for the AI agent.

Used to answer questions about budgets, totals, line items, and
acceptance status.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetLine, Invoice, Order


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


def _budget_by_number_or_id(
    db: Session, budget_number: str | None, budget_id: int | None
) -> Budget | None:
    """Resolve a :class:`Budget` by number or by id, whichever is set.

    Returns ``None`` when neither is provided or when no row matches.
    Falls back to the pre-normalised column (``budget_number_normalized``)
    when the exact match fails so a search for ``"260009"`` still finds
    a budget stored as ``" 260 009 "``.
    """
    if budget_id is not None:
        return db.get(Budget, int(budget_id))
    if not budget_number:
        return None
    budget = db.scalar(select(Budget).where(Budget.budget_number == budget_number).limit(1))
    if budget is not None:
        return budget
    # Fallback: normalised lookup (whitespace / hyphen insensitive).
    raw = unicodedata.normalize("NFKD", budget_number)
    raw = raw.encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[\s\-_/.,]", "", raw).lower()
    if not norm:
        return None
    return db.scalar(select(Budget).where(Budget.budget_number_normalized == norm).limit(1))


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
            select(BudgetLine)
            .where(BudgetLine.budget_id == budget.id)
            .order_by(BudgetLine.id.asc())
        ).all()
    )
    lines_total = 0.0
    for ln in lines:
        if ln.total_price is not None:
            lines_total += float(ln.total_price)
    match = (
        budget.total_amount is not None
        and lines
        and abs(lines_total - float(budget.total_amount))
        <= max(1.0, float(budget.total_amount) * 0.01)
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
    order_ids = list(db.scalars(select(Order.id).where(Order.related_budget_id == budget.id)).all())
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
        "orders": [{"order_id": oid, "invoiced": False} for oid in order_ids],
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
