from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetLine
from app.schemas.integration import IntegrationSource, IntegrationToolExecuteResponse
from app.services.integration_security import IntegrationContext
from app.services.integration_tools.common import (
    GetBudgetByNumberArgs,
    SearchBudgetsArgs,
    _allows_budget_search,
    _average,
    _can_view_prices,
    _document_source,
    _filter_budgets_for_context,
    _redactions_for_policy,
    _response,
)
from app.tools import internal


def execute_get_budget_by_number(
    db: Session,
    context: IntegrationContext,
    args: GetBudgetByNumberArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    budgets = _filter_budgets_for_context(
        db,
        list(db.scalars(select(Budget).where(Budget.budget_number == args.budget_number)).all()),
        context,
    )
    if not budgets:
        return _response(
            request_id,
            "get_budget_by_number",
            context,
            data={"status": "not_found", "budget_number": args.budget_number},
            warnings=[
                "Presupuesto no encontrado por coincidencia exacta dentro del scope autorizado."
            ],
        )
    if len(budgets) > 1:
        sources = [_budget_source(db, budget, context) for budget in budgets[:5]]
        return _response(
            request_id,
            "get_budget_by_number",
            context,
            data={
                "status": "conflict",
                "budget_number": args.budget_number,
                "matches": len(budgets),
            },
            sources=sources,
            confidence=_average([budget.confidence for budget in budgets]),
            warnings=[
                "Hay mas de un presupuesto con el mismo numero exacto dentro del scope autorizado; requiere aclaracion humana."
            ],
            redactions=_redactions_for_policy(context),
        )
    budget = budgets[0]
    lines = list(
        db.scalars(
            select(BudgetLine)
            .where(BudgetLine.budget_id == budget.id)
            .order_by(BudgetLine.id.asc())
        ).all()
    )
    return _response(
        request_id,
        "get_budget_by_number",
        context,
        data=_budget_payload(budget, lines, context),
        sources=[_budget_source(db, budget, context)],
        confidence=budget.confidence,
        redactions=_redactions_for_policy(context),
    )


def execute_search_budgets(
    db: Session,
    context: IntegrationContext,
    args: SearchBudgetsArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    from fastapi import HTTPException, status

    if not _allows_budget_search(context):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Tool not allowed by access policy"
        )
    budgets = _filter_budgets_for_context(
        db, internal.search_budgets(db, args.query, status=args.status), context
    )[: args.limit]
    data = []
    sources = []
    for budget in budgets:
        lines = list(
            db.scalars(
                select(BudgetLine)
                .where(BudgetLine.budget_id == budget.id)
                .order_by(BudgetLine.id.asc())
            ).all()
        )
        data.append(_budget_payload(budget, lines, context))
        sources.append(_budget_source(db, budget, context))
    return _response(
        request_id,
        "search_budgets",
        context,
        data=data,
        sources=sources,
        confidence=_average([budget.confidence for budget in budgets]),
        redactions=_redactions_for_policy(context),
    )


def execute_get_accepted_budgets_without_order(
    db: Session,
    context: IntegrationContext,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    budgets = _filter_budgets_for_context(
        db, internal.get_accepted_budgets_without_order(db), context
    )
    data = [_budget_payload(budget, [], context) for budget in budgets]
    sources = [_budget_source(db, budget, context) for budget in budgets[:10]]
    return _response(
        request_id,
        "get_accepted_budgets_without_order",
        context,
        data=data,
        sources=sources,
        redactions=_redactions_for_policy(context),
    )


def _budget_payload(budget: Budget, lines: list[BudgetLine], context: IntegrationContext) -> dict:
    payload = {
        "budget_number": budget.budget_number,
        "status": budget.status,
        "client_name": budget.client_name,
        "accepted_detected": budget.accepted_detected,
        "confidence": budget.confidence,
        "lines": [
            {
                "reference": line.reference,
                "description": line.description,
                "quantity": line.quantity,
                "unit": line.unit,
                "confidence": line.confidence,
            }
            for line in lines
        ],
    }
    if _can_view_prices(context):
        payload["total_amount"] = budget.total_amount
        payload["currency"] = budget.currency
        for line_payload, line in zip(payload["lines"], lines, strict=False):
            line_payload["unit_price"] = line.unit_price
            line_payload["total_price"] = line.total_price
    return payload


def _budget_source(db: Session, budget: Budget, context: IntegrationContext) -> IntegrationSource:
    from app.models import Document

    document = db.get(Document, budget.document_id)
    if not document:
        return IntegrationSource(document_id=budget.document_id, confidence=budget.confidence)
    return _document_source(db, document, context, confidence=budget.confidence)
