from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.integration import IntegrationToolExecuteResponse
from app.services.integration_tools.common import (
    PlanIdArgs,
    QueryArgs,
    RoomMeasurementArgs,
    _can_access_plan,
    _filter_records_for_context,
    _model_dict,
    _response,
)
from app.services.integration_security import IntegrationContext
from app.tools import internal


def execute_search_plans(
    db: Session,
    context: IntegrationContext,
    args: QueryArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    plans = _filter_records_for_context(db, internal.search_plans(db, args.query), context)
    return _response(
        request_id, "search_plans", context, data=[_model_dict(plan) for plan in plans]
    )


def execute_get_plan_rooms(
    db: Session,
    context: IntegrationContext,
    args: PlanIdArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    if not _can_access_plan(db, args.plan_id, context):
        return _response(request_id, "get_plan_rooms", context, data=[])
    rooms = internal.get_plan_rooms(db, args.plan_id)
    return _response(
        request_id, "get_plan_rooms", context, data=[_model_dict(room) for room in rooms]
    )


def execute_get_plan_dimensions(
    db: Session,
    context: IntegrationContext,
    args: PlanIdArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    if not _can_access_plan(db, args.plan_id, context):
        return _response(request_id, "get_plan_dimensions", context, data=[])
    dimensions = internal.get_plan_dimensions(db, args.plan_id)
    return _response(
        request_id,
        "get_plan_dimensions",
        context,
        data=[_model_dict(dimension) for dimension in dimensions],
    )


def execute_get_room_measurements(
    db: Session,
    context: IntegrationContext,
    args: RoomMeasurementArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    if not _can_access_plan(db, args.plan_id, context):
        return _response(request_id, "get_room_measurements", context, data=[])
    rooms = internal.get_room_measurements(db, args.plan_id, args.room_name)
    return _response(
        request_id, "get_room_measurements", context, data=[_model_dict(room) for room in rooms]
    )
