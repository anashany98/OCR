from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.models import Budget, BudgetLine, Invoice, Order, OrderLine, ReconciliationIssue
from app.services.tenant_access import AccessScope


PRICE_FIELD_NAMES = {
    "total_amount",
    "unit_price",
    "total_price",
    "currency",
    "expected_amount",
    "actual_amount",
}


def can_view_business_prices(scope: AccessScope | None) -> bool:
    return scope is None or scope.can_view_prices


def redact_business_payload_for_scope(payload: Any, scope: AccessScope | None) -> Any:
    """Return a copy of a structured business payload with price fields nulled.

    This is for JSON/dict payloads such as AI resolved-document snapshots.
    Text snippets are still handled by ``redact_sensitive_text``.
    """
    if can_view_business_prices(scope):
        return deepcopy(payload)
    return _redact_structured_prices(deepcopy(payload))


def budget_read_payload(budget: Budget, scope: AccessScope | None) -> dict[str, Any]:
    return _hide_prices_if_needed(
        {
            "id": budget.id,
            "document_id": budget.document_id,
            "budget_number": budget.budget_number,
            "client_name": budget.client_name,
            "date": budget.date,
            "total_amount": budget.total_amount,
            "currency": budget.currency,
            "status": budget.status,
            "accepted_detected": budget.accepted_detected,
            "confidence": budget.confidence,
            "created_at": budget.created_at,
        },
        scope,
    )


def budget_line_read_payload(line: BudgetLine, scope: AccessScope | None) -> dict[str, Any]:
    return _hide_prices_if_needed(
        {
            "id": line.id,
            "budget_id": line.budget_id,
            "reference": line.reference,
            "description": line.description,
            "quantity": line.quantity,
            "unit": line.unit,
            "unit_price": line.unit_price,
            "total_price": line.total_price,
            "confidence": line.confidence,
        },
        scope,
    )


def order_read_payload(order: Order, scope: AccessScope | None) -> dict[str, Any]:
    return _hide_prices_if_needed(
        {
            "id": order.id,
            "document_id": order.document_id,
            "order_number": order.order_number,
            "supplier_name": order.supplier_name,
            "client_name": order.client_name,
            "date": order.date,
            "total_amount": order.total_amount,
            "currency": order.currency,
            "related_budget_id": order.related_budget_id,
            "confidence": order.confidence,
            "created_at": order.created_at,
        },
        scope,
    )


def order_line_read_payload(line: OrderLine, scope: AccessScope | None) -> dict[str, Any]:
    return _hide_prices_if_needed(
        {
            "id": line.id,
            "order_id": line.order_id,
            "reference": line.reference,
            "description": line.description,
            "quantity": line.quantity,
            "unit": line.unit,
            "unit_price": line.unit_price,
            "total_price": line.total_price,
            "confidence": line.confidence,
        },
        scope,
    )


def invoice_read_payload(invoice: Invoice, scope: AccessScope | None) -> dict[str, Any]:
    return _hide_prices_if_needed(
        {
            "id": invoice.id,
            "document_id": invoice.document_id,
            "invoice_number": invoice.invoice_number,
            "supplier_name": invoice.supplier_name,
            "client_name": invoice.client_name,
            "date": invoice.date,
            "total_amount": invoice.total_amount,
            "currency": invoice.currency,
            "related_order_id": invoice.related_order_id,
            "confidence": invoice.confidence,
            "created_at": invoice.created_at,
        },
        scope,
    )


def reconciliation_issue_read_payload(
    issue: ReconciliationIssue, scope: AccessScope | None
) -> dict[str, Any]:
    return _hide_prices_if_needed(
        {
            "id": issue.id,
            "kind": issue.kind,
            "severity": issue.severity,
            "status": issue.status,
            "title": issue.title,
            "description": issue.description,
            "budget_id": issue.budget_id,
            "order_id": issue.order_id,
            "invoice_id": issue.invoice_id,
            "document_id": issue.document_id,
            "expected_amount": issue.expected_amount,
            "actual_amount": issue.actual_amount,
            "resolution_notes": issue.resolution_notes,
            "created_at": issue.created_at,
            "updated_at": issue.updated_at,
        },
        scope,
    )


def _hide_prices_if_needed(payload: dict[str, Any], scope: AccessScope | None) -> dict[str, Any]:
    if can_view_business_prices(scope):
        return payload
    return {key: (None if key in PRICE_FIELD_NAMES else value) for key, value in payload.items()}


def _redact_structured_prices(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: None if key in PRICE_FIELD_NAMES else _redact_structured_prices(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_structured_prices(item) for item in value]
    return value
