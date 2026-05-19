from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import Document, Invoice, User
from app.schemas.professional import InvoiceCreate, InvoiceRead
from app.services.audit import write_audit
from app.services.tenant_access import filter_records_by_document_scope, resolve_user_access_scope

router = APIRouter()


@router.get("", response_model=list[InvoiceRead])
def list_invoices(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Invoice]:
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (Invoice.invoice_number.ilike(pattern))
            | (Invoice.supplier_name.ilike(pattern))
            | (Invoice.client_name.ilike(pattern))
        )
    invoices = list(db.scalars(stmt.limit(limit)).all())
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return invoices
    allowed_document_ids = {record.document_id for record in filter_records_by_document_scope(db, invoices, scope)}
    return [invoice for invoice in invoices if invoice.document_id in allowed_document_ids]


@router.post("", response_model=InvoiceRead)
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "gestor"))) -> Invoice:
    document = db.get(Document, payload.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    invoice = Invoice(**payload.model_dump())
    db.add(invoice)
    db.flush()
    write_audit(db, user=user, action="invoice_created", entity_type="invoice", entity_id=invoice.id)
    db.commit()
    db.refresh(invoice)
    return invoice
