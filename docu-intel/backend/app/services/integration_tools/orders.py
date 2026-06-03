from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Order
from app.schemas.integration import IntegrationToolExecuteResponse
from app.services.integration_tools.common import (
    OrderNumberArgs,
    QueryArgs,
    _can_view_prices,
    _document_id_allowed_for_context,
    _filter_records_for_context,
    _model_dict,
    _response,
)
from app.services.integration_security import IntegrationContext
from app.tools import internal


def execute_search_orders(
    db: Session,
    context: IntegrationContext,
    args: QueryArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    orders = _filter_records_for_context(db, internal.search_orders(db, args.query), context)[: args.limit]
    return _response(request_id, "search_orders", context, data=[_order_payload(order, context) for order in orders])


def execute_get_order_by_number(
    db: Session,
    context: IntegrationContext,
    args: OrderNumberArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    order = internal.get_order_by_number(db, args.order_number)
    if order and not _document_id_allowed_for_context(db, order.document_id, context):
        order = None
    data = _order_payload(order, context) if order else {"status": "not_found", "order_number": args.order_number}
    return _response(request_id, "get_order_by_number", context, data=data)


def _order_payload(order: Order | None, context: IntegrationContext) -> dict:
    if not order:
        return {}
    payload = {
        "order_number": order.order_number,
        "supplier_name": order.supplier_name,
        "client_name": order.client_name,
        "date": order.date.isoformat() if order.date else None,
        "related_budget_id": order.related_budget_id,
        "confidence": order.confidence,
    }
    if _can_view_prices(context):
        payload["total_amount"] = order.total_amount
        payload["currency"] = order.currency
    return payload
