from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetLine, Document, DocumentBlock, DocumentPage, Order
from app.schemas.integration import (
    IntegrationManifest,
    IntegrationSource,
    IntegrationToolDefinition,
    IntegrationToolExecuteResponse,
)
from app.services.access_policy import policy_allows_budget_search, policy_allows_prices
from app.services.integration_security import IntegrationContext
from app.services.redaction import redact_sensitive_text
from app.services.search_service import search_hybrid, search_text
from app.services.tenant_access import (
    can_access_document,
    filter_document_ids_for_scope,
    filter_records_by_document_scope,
    filter_search_results_for_scope,
    scope_payload,
)
from app.tools import internal

REDACTED_BUDGET_FIELDS = [
    "budget.total_amount",
    "budget.currency",
    "budget_lines.unit_price",
    "budget_lines.total_price",
    "ocr.money_amounts",
]


class GetBudgetByNumberArgs(BaseModel):
    budget_number: str = Field(min_length=1, max_length=120)


class SearchBudgetsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    status: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


class QueryArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    document_type: str | None = None


class DocumentIdArgs(BaseModel):
    document_id: int = Field(ge=1)
    page_number: int | None = Field(default=None, ge=1)


class OrderNumberArgs(BaseModel):
    order_number: str = Field(min_length=1, max_length=120)


class PlanIdArgs(BaseModel):
    plan_id: int = Field(ge=1)


class RoomMeasurementArgs(BaseModel):
    plan_id: int = Field(ge=1)
    room_name: str = Field(min_length=1, max_length=120)


class EntitySearchArgs(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=200)


class HybridSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    filters: dict | None = None
    limit: int = Field(default=10, ge=1, le=50)


TOOL_ARGUMENTS = {
    "get_budget_by_number": GetBudgetByNumberArgs,
    "search_budgets": SearchBudgetsArgs,
    "search_documents": QueryArgs,
    "get_document": DocumentIdArgs,
    "get_document_blocks": DocumentIdArgs,
    "get_accepted_budgets_without_order": BaseModel,
    "search_orders": QueryArgs,
    "get_order_by_number": OrderNumberArgs,
    "get_related_documents": DocumentIdArgs,
    "search_plans": QueryArgs,
    "get_plan_rooms": PlanIdArgs,
    "get_plan_dimensions": PlanIdArgs,
    "get_room_measurements": RoomMeasurementArgs,
    "search_entities": EntitySearchArgs,
    "hybrid_search": HybridSearchArgs,
}


def build_manifest() -> IntegrationManifest:
    return IntegrationManifest(
        version="1.1",
        rules=[
            "No pedir SQL ni intentar acceder a tablas directamente.",
            "No mostrar precios si la respuesta incluye redactions.",
            "No mezclar presupuestos: usa get_budget_by_number con coincidencia exacta.",
            "Para consultas operativas usa una sesion firmada de presupuesto creada con POST /integrations/v1/sessions.",
            "Si hay sesion firmada, todas las busquedas se limitan al budget_scope_id de esa sesion.",
            "Si una tool devuelve not_found, responde que no se puede confirmar con la informacion disponible.",
            "Citar siempre las fuentes devueltas por Docu-Intel.",
            "No asumir que un presupuesto no existe globalmente; solo existe o no existe dentro del scope autorizado.",
            "Si el usuario menciona otro presupuesto distinto al de la sesion, no cambies de scope: pide una nueva sesion autorizada.",
        ],
        tools=[
            IntegrationToolDefinition(
                name=name,
                description=_tool_description(name),
                arguments_schema=_schema_for(model),
                scopes=["read"],
            )
            for name, model in TOOL_ARGUMENTS.items()
        ],
    )


def execute_integration_tool(
    db: Session,
    *,
    context: IntegrationContext,
    tool: str,
    arguments: dict,
) -> IntegrationToolExecuteResponse:
    if tool not in TOOL_ARGUMENTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown integration tool")
    parsed = _parse_arguments(tool, arguments)
    request_id = str(uuid4())

    if tool == "get_budget_by_number":
        response = _get_budget_by_number(db, context, parsed, request_id)
    elif tool == "search_budgets":
        response = _search_budgets(db, context, parsed, request_id)
    else:
        response = _execute_generic_tool(db, context, tool, parsed, request_id)
    return response


def _get_budget_by_number(
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
            warnings=["Presupuesto no encontrado por coincidencia exacta dentro del scope autorizado."],
        )
    if len(budgets) > 1:
        sources = [_budget_source(db, budget, context) for budget in budgets[:5]]
        return _response(
            request_id,
            "get_budget_by_number",
            context,
            data={"status": "conflict", "budget_number": args.budget_number, "matches": len(budgets)},
            sources=sources,
            confidence=_average([budget.confidence for budget in budgets]),
            warnings=["Hay mas de un presupuesto con el mismo numero exacto dentro del scope autorizado; requiere aclaracion humana."],
            redactions=_redactions_for_policy(context),
        )
    budget = budgets[0]
    lines = list(db.scalars(select(BudgetLine).where(BudgetLine.budget_id == budget.id).order_by(BudgetLine.id.asc())).all())
    return _response(
        request_id,
        "get_budget_by_number",
        context,
        data=_budget_payload(budget, lines, context),
        sources=[_budget_source(db, budget, context)],
        confidence=budget.confidence,
        redactions=_redactions_for_policy(context),
    )


def _search_budgets(
    db: Session,
    context: IntegrationContext,
    args: SearchBudgetsArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    if not _allows_budget_search(context):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tool not allowed by access policy")
    budgets = _filter_budgets_for_context(db, internal.search_budgets(db, args.query, status=args.status), context)[: args.limit]
    data = []
    sources = []
    for budget in budgets:
        lines = list(db.scalars(select(BudgetLine).where(BudgetLine.budget_id == budget.id).order_by(BudgetLine.id.asc())).all())
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


def _execute_generic_tool(
    db: Session,
    context: IntegrationContext,
    tool: str,
    args: BaseModel,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    if tool == "search_documents":
        results = search_text(
            db,
            args.query,
            limit=args.limit * 5,
            filters={"document_type": args.document_type} if args.document_type else None,
        )
        results = _filter_search_results_for_context(db, results, context)[: args.limit]
        return _search_response(request_id, tool, context, results)
    if tool == "hybrid_search":
        filters = dict(args.filters or {})
        filters["limit"] = args.limit
        results = search_hybrid(db, args.query, limit=args.limit * 5, filters=filters)
        results = _filter_search_results_for_context(db, results, context)[: args.limit]
        return _search_response(request_id, tool, context, results)
    if tool == "get_document":
        document = db.get(Document, args.document_id)
        if not _can_access_document_for_context(db, document, context):
            document = None
        data = _document_payload(document) if document else {"status": "not_found", "document_id": args.document_id}
        return _response(request_id, tool, context, data=data, sources=[] if not document else [_document_source(db, document, context)])
    if tool == "get_document_blocks":
        document = db.get(Document, args.document_id)
        if not _can_access_document_for_context(db, document, context):
            return _response(request_id, tool, context, data=[])
        blocks = internal.get_document_blocks(db, args.document_id, args.page_number)
        return _response(request_id, tool, context, data=[_block_payload(block, context) for block in blocks])
    if tool == "get_accepted_budgets_without_order":
        budgets = _filter_budgets_for_context(db, internal.get_accepted_budgets_without_order(db), context)
        data = [_budget_payload(budget, [], context) for budget in budgets]
        sources = [_budget_source(db, budget, context) for budget in budgets[:10]]
        return _response(request_id, tool, context, data=data, sources=sources, redactions=_redactions_for_policy(context))
    if tool == "search_orders":
        orders = _filter_records_for_context(db, internal.search_orders(db, args.query), context)[: args.limit]
        return _response(request_id, tool, context, data=[_order_payload(order, context) for order in orders])
    if tool == "get_order_by_number":
        order = internal.get_order_by_number(db, args.order_number)
        if order and not _document_id_allowed_for_context(db, order.document_id, context):
            order = None
        data = _order_payload(order, context) if order else {"status": "not_found", "order_number": args.order_number}
        return _response(request_id, tool, context, data=data)
    if tool == "get_related_documents":
        documents = internal.get_related_documents(db, args.document_id)
        documents = [document for document in documents if _can_access_document_for_context(db, document, context)]
        return _response(request_id, tool, context, data=[_document_payload(document) for document in documents])
    if tool == "search_plans":
        plans = _filter_records_for_context(db, internal.search_plans(db, args.query), context)
        return _response(request_id, tool, context, data=[_model_dict(plan) for plan in plans])
    if tool == "get_plan_rooms":
        if not _can_access_plan(db, args.plan_id, context):
            return _response(request_id, tool, context, data=[])
        rooms = internal.get_plan_rooms(db, args.plan_id)
        return _response(request_id, tool, context, data=[_model_dict(room) for room in rooms])
    if tool == "get_plan_dimensions":
        if not _can_access_plan(db, args.plan_id, context):
            return _response(request_id, tool, context, data=[])
        dimensions = internal.get_plan_dimensions(db, args.plan_id)
        return _response(request_id, tool, context, data=[_model_dict(dimension) for dimension in dimensions])
    if tool == "get_room_measurements":
        if not _can_access_plan(db, args.plan_id, context):
            return _response(request_id, tool, context, data=[])
        rooms = internal.get_room_measurements(db, args.plan_id, args.room_name)
        return _response(request_id, tool, context, data=[_model_dict(room) for room in rooms])
    if tool == "search_entities":
        entities = internal.search_entities(db, args.entity_type, args.value)
        allowed_document_ids = _filter_document_ids_for_context(db, [entity.document_id for entity in entities], context)
        entities = [entity for entity in entities if entity.document_id in allowed_document_ids]
        return _response(request_id, tool, context, data=[_model_dict(entity) for entity in entities])
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown integration tool")


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
    document = db.get(Document, budget.document_id)
    if not document:
        return IntegrationSource(document_id=budget.document_id, confidence=budget.confidence)
    return _document_source(db, document, context, confidence=budget.confidence)


def _document_source(
    db: Session,
    document: Document,
    context: IntegrationContext,
    *,
    confidence: float | None = None,
) -> IntegrationSource:
    page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.page_number.asc()).limit(1))
    excerpt = page.text[:500] if page and page.text else ""
    if not _can_view_prices(context):
        excerpt = redact_sensitive_text(excerpt)
    return IntegrationSource(
        document_id=document.id,
        filename=document.original_filename,
        page_number=page.page_number if page else None,
        block_id=None,
        excerpt=excerpt,
        confidence=confidence if confidence is not None else document.confidence,
    )


def _block_payload(block: DocumentBlock, context: IntegrationContext) -> dict:
    text = block.text or ""
    if not _can_view_prices(context):
        text = redact_sensitive_text(text)
    return {
        "id": block.id,
        "document_id": block.document_id,
        "page_number": block.page_number,
        "block_type": block.block_type,
        "text": text,
        "confidence": block.confidence,
    }


def _search_response(request_id: str, tool: str, context: IntegrationContext, results) -> IntegrationToolExecuteResponse:
    data = []
    sources = []
    for result in results:
        excerpt = result.excerpt or ""
        if not _can_view_prices(context):
            excerpt = redact_sensitive_text(excerpt)
        item = {
            "document_id": result.document_id,
            "filename": result.original_filename,
            "document_type": result.document_type,
            "status": result.status,
            "page_number": result.page_number,
            "block_id": result.block_id,
            "score": result.score,
            "excerpt": excerpt,
            "ocr_confidence": result.ocr_confidence,
        }
        data.append(item)
        sources.append(
            IntegrationSource(
                document_id=result.document_id,
                filename=result.original_filename,
                page_number=result.page_number,
                block_id=result.block_id,
                excerpt=excerpt,
                confidence=result.ocr_confidence,
            )
        )
    return _response(
        request_id,
        tool,
        context,
        data=data,
        sources=sources,
        confidence=_average([source.confidence for source in sources]),
        redactions=_redactions_for_policy(context),
    )


def _document_payload(document: Document | None) -> dict:
    if not document:
        return {}
    return {
        "id": document.id,
        "original_filename": document.original_filename,
        "document_type": document.document_type,
        "status": document.status,
        "confidence": document.confidence,
        "page_count": document.page_count,
    }


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


def _model_dict(item) -> dict:
    data = {}
    for column in item.__table__.columns:
        value = getattr(item, column.name)
        data[column.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return data


def _response(
    request_id: str,
    tool: str,
    context: IntegrationContext,
    *,
    data,
    sources: list[IntegrationSource] | None = None,
    confidence: float | None = None,
    warnings: list[str] | None = None,
    redactions: list[str] | None = None,
) -> IntegrationToolExecuteResponse:
    return IntegrationToolExecuteResponse(
        request_id=request_id,
        tool=tool,
        technician_id=context.technician_id,
        data=data,
        sources=sources or [],
        confidence=confidence,
        warnings=warnings or [],
        redactions=redactions or [],
        scope=_scope_payload(context),
    )


def _redactions_for_policy(context: IntegrationContext) -> list[str]:
    return [] if _can_view_prices(context) else list(REDACTED_BUDGET_FIELDS)


def _can_view_prices(context: IntegrationContext) -> bool:
    if context.budget_session:
        return bool(context.budget_session.can_see_amounts and (policy_allows_prices(context.policy) or context.access_scope.can_view_prices))
    return bool(policy_allows_prices(context.policy) or context.access_scope.can_view_prices)


def _allows_budget_search(context: IntegrationContext) -> bool:
    return bool(policy_allows_budget_search(context.policy) or context.access_scope.can_search_budgets)


def _can_access_plan(db: Session, plan_id: int, context: IntegrationContext) -> bool:
    from app.models import Plan

    plan = db.get(Plan, plan_id)
    if not plan:
        return False
    return _document_id_allowed_for_context(db, plan.document_id, context)


def _scope_payload(context: IntegrationContext) -> dict:
    payload = scope_payload(context.access_scope)
    if context.budget_session:
        payload.update(
            {
                "budget_scope_id": context.budget_session.budget_scope_id,
                "budget_code": context.budget_session.budget_code,
                "budget_session": True,
                "session_can_see_amounts": context.budget_session.can_see_amounts,
            }
        )
    return payload


def _filter_budgets_for_context(db: Session, budgets, context: IntegrationContext) -> list[Budget]:
    return _filter_records_for_context(db, budgets, context)


def _filter_records_for_context(db: Session, records, context: IntegrationContext) -> list:
    records_list = list(records)
    if not context.budget_session:
        return filter_records_by_document_scope(db, records_list, context.access_scope)
    allowed_document_ids = _filter_document_ids_for_context(db, [record.document_id for record in records_list], context)
    return [record for record in records_list if record.document_id in allowed_document_ids]


def _filter_search_results_for_context(db: Session, results, context: IntegrationContext) -> list:
    results_list = list(results)
    if not context.budget_session:
        return filter_search_results_for_scope(db, results_list, context.access_scope)
    allowed_document_ids = _filter_document_ids_for_context(db, [result.document_id for result in results_list], context)
    return [result for result in results_list if result.document_id in allowed_document_ids]


def _filter_document_ids_for_context(db: Session, document_ids, context: IntegrationContext) -> set[int]:
    if not context.budget_session:
        return filter_document_ids_for_scope(db, document_ids, context.access_scope)
    ids = {int(document_id) for document_id in document_ids if document_id is not None}
    if not ids:
        return set()
    rows = db.execute(
        select(Document.id)
        .where(Document.id.in_(ids))
        .where(Document.deleted_at.is_(None))
        .where(Document.budget_scope_id == context.budget_session.budget_scope_id)
    ).all()
    return {int(row[0]) for row in rows}


def _document_id_allowed_for_context(db: Session, document_id: int | None, context: IntegrationContext) -> bool:
    if document_id is None:
        return False
    return int(document_id) in _filter_document_ids_for_context(db, [document_id], context)


def _can_access_document_for_context(db: Session, document: Document | None, context: IntegrationContext) -> bool:
    if not context.budget_session:
        return can_access_document(db, document, context.access_scope)
    if not document or document.deleted_at is not None:
        return False
    return document.budget_scope_id == context.budget_session.budget_scope_id


def _average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _parse_arguments(tool: str, arguments: dict) -> BaseModel:
    model = TOOL_ARGUMENTS[tool]
    try:
        if model is BaseModel:
            return model()
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from None


def _schema_for(model: type[BaseModel]) -> dict:
    if model is BaseModel:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    return model.model_json_schema()


def _tool_description(name: str) -> str:
    descriptions = {
        "get_budget_by_number": "Consulta un presupuesto por numero exacto y aplica redaccion segun politica.",
        "search_budgets": "Busca presupuestos; requiere politica con permiso explicito de busqueda.",
        "hybrid_search": "Busca documentos por texto y embeddings con excerpts saneados.",
    }
    return descriptions.get(name, f"Ejecuta la tool controlada {name}.")
