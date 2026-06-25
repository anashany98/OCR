from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.services.integration_security import IntegrationContext
from app.services.integration_tools.budgets import (
    execute_get_accepted_budgets_without_order,
    execute_get_budget_by_number,
    execute_search_budgets,
)
from app.services.integration_tools.common import (
    REDACTED_BUDGET_FIELDS,
    TOOL_ARGUMENTS,
    _parse_arguments,
    build_manifest,
)
from app.services.integration_tools.documents import (
    execute_get_document,
    execute_get_document_blocks,
    execute_get_related_documents,
)
from app.services.integration_tools.entities import (
    execute_search_entities,
)
from app.services.integration_tools.learning import (
    execute_get_improvement_candidates,
    execute_propose_classification_correction,
    execute_propose_classification_rule,
    execute_propose_entity_link,
    execute_submit_quality_feedback,
)
from app.services.integration_tools.orders import (
    execute_get_order_by_number,
    execute_search_orders,
)
from app.services.integration_tools.plans import (
    execute_get_plan_dimensions,
    execute_get_plan_rooms,
    execute_get_room_measurements,
    execute_search_plans,
)
from app.services.integration_tools.search import (
    execute_hybrid_search,
    execute_search_documents,
)

__all__ = [
    "REDACTED_BUDGET_FIELDS",
    "build_manifest",
    "execute_integration_tool",
]


def execute_integration_tool(
    db: Session,
    *,
    context: IntegrationContext,
    tool: str,
    arguments: dict,
):
    from uuid import uuid4

    if tool not in TOOL_ARGUMENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown integration tool"
        )
    parsed = _parse_arguments(tool, arguments)
    request_id = str(uuid4())

    if tool == "get_budget_by_number":
        return execute_get_budget_by_number(db, context, parsed, request_id)
    if tool == "search_budgets":
        return execute_search_budgets(db, context, parsed, request_id)
    if tool == "search_documents":
        return execute_search_documents(db, context, parsed, request_id)
    if tool == "hybrid_search":
        return execute_hybrid_search(db, context, parsed, request_id)
    if tool == "get_document":
        return execute_get_document(db, context, parsed, request_id)
    if tool == "get_document_blocks":
        return execute_get_document_blocks(db, context, parsed, request_id)
    if tool == "get_accepted_budgets_without_order":
        return execute_get_accepted_budgets_without_order(db, context, request_id)
    if tool == "search_orders":
        return execute_search_orders(db, context, parsed, request_id)
    if tool == "get_order_by_number":
        return execute_get_order_by_number(db, context, parsed, request_id)
    if tool == "get_related_documents":
        return execute_get_related_documents(db, context, parsed, request_id)
    if tool == "search_plans":
        return execute_search_plans(db, context, parsed, request_id)
    if tool == "get_plan_rooms":
        return execute_get_plan_rooms(db, context, parsed, request_id)
    if tool == "get_plan_dimensions":
        return execute_get_plan_dimensions(db, context, parsed, request_id)
    if tool == "get_room_measurements":
        return execute_get_room_measurements(db, context, parsed, request_id)
    if tool == "search_entities":
        return execute_search_entities(db, context, parsed, request_id)
    if tool == "propose_classification_correction":
        return execute_propose_classification_correction(db, context, parsed, request_id)
    if tool == "propose_entity_link":
        return execute_propose_entity_link(db, context, parsed, request_id)
    if tool == "propose_classification_rule":
        return execute_propose_classification_rule(db, context, parsed, request_id)
    if tool == "submit_quality_feedback":
        return execute_submit_quality_feedback(db, context, parsed, request_id)
    if tool == "get_improvement_candidates":
        return execute_get_improvement_candidates(db, context, parsed, request_id)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown integration tool")
