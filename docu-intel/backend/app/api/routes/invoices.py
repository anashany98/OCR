from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import Document, Invoice, User
from app.schemas.professional import InvoiceCreate, InvoiceRead
from app.services.audit import write_audit
from app.services.business_redaction import invoice_read_payload
from app.services.tenant_access import (
    apply_access_predicates,
    can_access_document,
    filter_records_by_document_scope,
    resolve_user_access_scope,
)

router = APIRouter()


@router.get("", response_model=list[InvoiceRead])
def list_invoices(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (Invoice.invoice_number.ilike(pattern))
            | (Invoice.supplier_name.ilike(pattern))
            | (Invoice.client_name.ilike(pattern))
        )
    scope = resolve_user_access_scope(db, user)
    if not scope.is_admin:
        stmt = apply_access_predicates(stmt, scope, document_column=Invoice.document_id)
    invoices = list(db.scalars(stmt.limit(limit)).all())
    if scope.is_admin:
        return [invoice_read_payload(invoice, scope) for invoice in invoices]
    # DATA-03: filter at the SQL layer so the page does not
    # contain out-of-scope invoices. The in-memory helper still
    # runs afterwards to drop any that hit ``denied_tags`` /
    # ``allowed_document_types``.
    allowed_document_ids = {
        record.document_id for record in filter_records_by_document_scope(db, invoices, scope)
    }
    return [
        invoice_read_payload(invoice, scope)
        for invoice in invoices
        if invoice.document_id in allowed_document_ids
    ]


@router.post("", response_model=InvoiceRead)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> dict:
    document = db.get(Document, payload.document_id)
    scope = resolve_user_access_scope(db, user)
    if not document or not can_access_document(db, document, scope):
        raise HTTPException(status_code=404, detail="Document not found")
    invoice = Invoice(**payload.model_dump())
    db.add(invoice)
    db.flush()
    write_audit(
        db, user=user, action="invoice_created", entity_type="invoice", entity_id=invoice.id
    )
    db.commit()
    db.refresh(invoice)
    return invoice_read_payload(invoice, scope)


# ---------------------------------------------------------------------------
# Aggregation endpoints
# ---------------------------------------------------------------------------

class MonthlyAggregation(BaseModel):
    year: int
    month: int
    total: float
    count: int


class SupplierAggregation(BaseModel):
    supplier_name: str
    total: float
    count: int


class YearlyAggregation(BaseModel):
    year: int
    total: float
    count: int


@router.get("/aggregate/monthly", response_model=list[MonthlyAggregation])
def aggregate_monthly(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = (
        select(
            func.extract("year", Invoice.date).label("year"),
            func.extract("month", Invoice.date).label("month"),
            func.coalesce(func.sum(Invoice.total_amount), 0.0).label("total"),
            func.count(Invoice.id).label("count"),
        )
        .where(Invoice.date.isnot(None))
        .where(func.extract("year", Invoice.date) == year)
        .group_by(
            func.extract("year", Invoice.date),
            func.extract("month", Invoice.date),
        )
        .order_by(func.extract("month", Invoice.date))
    )
    rows = db.execute(stmt).all()
    return [
        {"year": int(r.year), "month": int(r.month), "total": float(r.total), "count": r.count}
        for r in rows
    ]


@router.get("/aggregate/by-supplier", response_model=list[SupplierAggregation])
def aggregate_by_supplier(
    year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = (
        select(
            Invoice.supplier_name,
            func.coalesce(func.sum(Invoice.total_amount), 0.0).label("total"),
            func.count(Invoice.id).label("count"),
        )
        .where(Invoice.supplier_name.isnot(None))
        .group_by(Invoice.supplier_name)
        .order_by(func.coalesce(func.sum(Invoice.total_amount), 0.0).desc())
        .limit(limit)
    )
    if year is not None:
        stmt = stmt.where(func.extract("year", Invoice.date) == year)
    rows = db.execute(stmt).all()
    return [
        {"supplier_name": r.supplier_name, "total": float(r.total), "count": r.count}
        for r in rows
    ]


@router.get("/aggregate/yearly", response_model=list[YearlyAggregation])
def aggregate_yearly(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = (
        select(
            func.extract("year", Invoice.date).label("year"),
            func.coalesce(func.sum(Invoice.total_amount), 0.0).label("total"),
            func.count(Invoice.id).label("count"),
        )
        .where(Invoice.date.isnot(None))
        .group_by(func.extract("year", Invoice.date))
        .order_by(func.extract("year", Invoice.date).desc())
    )
    rows = db.execute(stmt).all()
    return [
        {"year": int(r.year), "total": float(r.total), "count": r.count}
        for r in rows
    ]
