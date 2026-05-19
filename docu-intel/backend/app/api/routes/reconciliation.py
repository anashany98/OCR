from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import Budget, Invoice, Order, ReconciliationIssue, User
from app.schemas.professional import ReconciliationIssueRead, ReconciliationIssueUpdate
from app.services.audit import write_audit

router = APIRouter()


@router.get("/issues", response_model=list[ReconciliationIssueRead])
def list_issues(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))) -> list[ReconciliationIssue]:
    return list(db.scalars(select(ReconciliationIssue).order_by(ReconciliationIssue.created_at.desc())).all())


@router.post("/issues/generate", response_model=list[ReconciliationIssueRead])
def generate_issues(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "gestor"))) -> list[ReconciliationIssue]:
    created: list[ReconciliationIssue] = []

    for budget in db.scalars(select(Budget).where(Budget.accepted_detected.is_(True))).all():
        has_order = db.scalar(select(Order.id).where(Order.related_budget_id == budget.id).limit(1))
        if not has_order:
            issue = _ensure_issue(
                db,
                kind="accepted_budget_without_order",
                budget_id=budget.id,
                title="Presupuesto aceptado sin pedido",
                description=f"El presupuesto {budget.budget_number or budget.id} está aceptado y no tiene pedido relacionado.",
                document_id=budget.document_id,
                expected_amount=budget.total_amount,
            )
            if issue:
                created.append(issue)

    for order in db.scalars(select(Order).where(Order.related_budget_id.is_(None))).all():
        issue = _ensure_issue(
            db,
            kind="order_without_budget",
            order_id=order.id,
            title="Pedido sin presupuesto",
            description=f"El pedido {order.order_number or order.id} no está enlazado a presupuesto.",
            document_id=order.document_id,
            actual_amount=order.total_amount,
        )
        if issue:
            created.append(issue)

    for invoice in db.scalars(select(Invoice).where(Invoice.related_order_id.is_(None))).all():
        issue = _ensure_issue(
            db,
            kind="invoice_without_order",
            invoice_id=invoice.id,
            title="Factura sin pedido",
            description=f"La factura {invoice.invoice_number or invoice.id} no está enlazada a pedido.",
            document_id=invoice.document_id,
            actual_amount=invoice.total_amount,
        )
        if issue:
            created.append(issue)

    write_audit(db, user=user, action="reconciliation_generated", entity_type="reconciliation_issue")
    db.commit()
    return list(db.scalars(select(ReconciliationIssue).order_by(ReconciliationIssue.created_at.desc())).all())


@router.patch("/issues/{issue_id}", response_model=ReconciliationIssueRead)
def update_issue(
    issue_id: int,
    payload: ReconciliationIssueUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ReconciliationIssue:
    issue = db.get(ReconciliationIssue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Reconciliation issue not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(issue, field, value)
    write_audit(db, user=user, action="reconciliation_issue_updated", entity_type="reconciliation_issue", entity_id=issue.id)
    db.commit()
    db.refresh(issue)
    return issue


def _ensure_issue(db: Session, *, kind: str, title: str, description: str, budget_id: int | None = None, order_id: int | None = None, invoice_id: int | None = None, document_id: int | None = None, expected_amount: float | None = None, actual_amount: float | None = None) -> ReconciliationIssue | None:
    existing = db.scalar(
        select(ReconciliationIssue)
        .where(ReconciliationIssue.kind == kind)
        .where(ReconciliationIssue.budget_id.is_(budget_id) if budget_id is None else ReconciliationIssue.budget_id == budget_id)
        .where(ReconciliationIssue.order_id.is_(order_id) if order_id is None else ReconciliationIssue.order_id == order_id)
        .where(ReconciliationIssue.invoice_id.is_(invoice_id) if invoice_id is None else ReconciliationIssue.invoice_id == invoice_id)
    )
    if existing:
        return None
    issue = ReconciliationIssue(
        kind=kind,
        severity="warning",
        status="pending",
        title=title,
        description=description,
        budget_id=budget_id,
        order_id=order_id,
        invoice_id=invoice_id,
        document_id=document_id,
        expected_amount=expected_amount,
        actual_amount=actual_amount,
    )
    db.add(issue)
    db.flush()
    return issue
