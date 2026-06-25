"""Invoice-related tools for the AI agent.

Used to answer questions about invoices, their origin orders, and
related budgets.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Invoice, Order


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
