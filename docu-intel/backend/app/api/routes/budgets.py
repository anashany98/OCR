from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import Budget, BudgetLine, Order, User
from app.schemas.business import BudgetLineRead, BudgetRead
from app.services.tenant_access import filter_records_by_document_scope, resolve_user_access_scope

router = APIRouter()


@router.get("", response_model=list[BudgetRead])
def list_budgets(
    q: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Budget]:
    stmt = select(Budget).order_by(Budget.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where((Budget.budget_number.ilike(pattern)) | (Budget.client_name.ilike(pattern)))
    if status:
        stmt = stmt.where(Budget.status == status)
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.limit(limit)).all())
    candidates = list(db.scalars(stmt.limit(max(limit * 5, 200))).all())
    return filter_records_by_document_scope(db, candidates, scope)[:limit]


@router.get("/accepted-without-order", response_model=list[BudgetRead])
def accepted_without_order(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Budget]:
    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    stmt = (
        select(Budget)
        .where(Budget.accepted_detected.is_(True))
        .where(Budget.id.not_in(ordered_budget_ids))
        .order_by(Budget.created_at.desc())
    )
    return filter_records_by_document_scope(db, list(db.scalars(stmt).all()), resolve_user_access_scope(db, user))


@router.get("/{budget_id}", response_model=BudgetRead)
def get_budget(budget_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Budget:
    budget = db.get(Budget, budget_id)
    if not budget or budget not in filter_records_by_document_scope(db, [budget], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


@router.get("/{budget_id}/lines", response_model=list[BudgetLineRead])
def get_budget_lines(budget_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[BudgetLine]:
    budget = db.get(Budget, budget_id)
    if not budget or budget not in filter_records_by_document_scope(db, [budget], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Budget not found")
    return list(db.scalars(select(BudgetLine).where(BudgetLine.budget_id == budget_id).order_by(BudgetLine.id.asc())).all())
