from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import Order, OrderLine, User
from app.schemas.business import OrderLineRead, OrderRead
from app.services.business_redaction import order_line_read_payload, order_read_payload
from app.services.tenant_access import (
    apply_access_predicates,
    filter_records_by_document_scope,
    resolve_user_access_scope,
)

router = APIRouter()


@router.get("", response_model=list[OrderRead])
def list_orders(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(Order).order_by(Order.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (Order.order_number.ilike(pattern))
            | (Order.supplier_name.ilike(pattern))
            | (Order.client_name.ilike(pattern))
        )
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        orders = list(db.scalars(stmt.limit(limit)).all())
        return [order_read_payload(order, scope) for order in orders]
    # DATA-03: same fix as in ``list_documents`` / ``list_budgets``.
    stmt = apply_access_predicates(stmt, scope, document_column=Order.document_id)
    candidates = list(db.scalars(stmt.limit(limit)).all())
    orders = filter_records_by_document_scope(db, candidates, scope)
    return [order_read_payload(order, scope) for order in orders]


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    order = db.get(Order, order_id)
    scope = resolve_user_access_scope(db, user)
    if not order or order not in filter_records_by_document_scope(db, [order], scope):
        raise HTTPException(status_code=404, detail="Order not found")
    return order_read_payload(order, scope)


@router.get("/{order_id}/lines", response_model=list[OrderLineRead])
def get_order_lines(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    order = db.get(Order, order_id)
    scope = resolve_user_access_scope(db, user)
    if not order or order not in filter_records_by_document_scope(db, [order], scope):
        raise HTTPException(status_code=404, detail="Order not found")
    lines = list(
        db.scalars(
            select(OrderLine).where(OrderLine.order_id == order_id).order_by(OrderLine.id.asc())
        ).all()
    )
    return [order_line_read_payload(line, scope) for line in lines]
