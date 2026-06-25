from __future__ import annotations

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Document, DocumentPage
from app.schemas.integration import (
    IntegrationManifest,
    IntegrationSource,
    IntegrationToolDefinition,
    IntegrationToolExecuteResponse,
)
from app.services.access_policy import policy_allows_budget_search, policy_allows_prices
from app.services.integration_security import IntegrationContext
from app.services.redaction import redact_sensitive_text
from app.services.tenant_access import (
    can_access_document,
    filter_document_ids_for_scope,
    filter_records_by_document_scope,
    filter_search_results_for_scope,
    get_document_access_metadata,
    scope_payload,
)

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


class ProposeClassificationCorrectionArgs(BaseModel):
    document_id: int = Field(ge=1)
    suggested_document_type: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: dict | None = None


class ProposeEntityLinkArgs(BaseModel):
    source_document_id: int = Field(ge=1)
    target_document_id: int = Field(ge=1)
    target_action: str = Field(default="link", min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ProposeClassificationRuleArgs(BaseModel):
    pattern_value: str = Field(min_length=1, max_length=500)
    target_class: str = Field(min_length=1, max_length=80)
    target_action: str = Field(default="classify_as", min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence_document_id: int | None = Field(default=None, ge=1)


class SubmitQualityFeedbackArgs(BaseModel):
    document_id: int = Field(ge=1)
    field: str = Field(min_length=1, max_length=120)
    old_value: str | None = Field(default=None, max_length=2000)
    suggested_value: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class GetImprovementCandidatesArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


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
    "propose_classification_correction": ProposeClassificationCorrectionArgs,
    "propose_entity_link": ProposeEntityLinkArgs,
    "propose_classification_rule": ProposeClassificationRuleArgs,
    "submit_quality_feedback": SubmitQualityFeedbackArgs,
    "get_improvement_candidates": GetImprovementCandidatesArgs,
}


def build_manifest() -> IntegrationManifest:
    return IntegrationManifest(
        version="1.4",
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
            "Puedes usar sandbox=true en tools/execute para validar argumentos, fuentes y redacciones antes de construir una respuesta final.",
            "Puedes usar propose_classification_correction, propose_entity_link, propose_classification_rule y submit_quality_feedback para sugerir mejoras; un admin debe aprobarlas antes de aplicarse.",
            "get_improvement_candidates devuelve documentos con baja confianza o que necesitan revision humana.",
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


def _tool_description(name: str) -> str:
    descriptions = {
        "get_budget_by_number": "Consulta un presupuesto por numero exacto y aplica redaccion segun politica.",
        "search_budgets": "Busca presupuestos; requiere politica con permiso explicito de busqueda.",
        "hybrid_search": "Busca documentos por texto y embeddings con excerpts saneados.",
        "propose_classification_correction": "Sugiere cambiar el tipo documental de un documento; requiere aprobacion de admin.",
        "propose_entity_link": "Sugiere vincular dos documentos (ej. presupuesto-pedido); requiere aprobacion.",
        "propose_classification_rule": "Propone una nueva regla de clasificacion (keyword/regex); requiere aprobacion.",
        "submit_quality_feedback": "Envia feedback estructurado sobre un campo extraido de un documento.",
        "get_improvement_candidates": "Devuelve documentos con baja confianza o que necesitan revision humana.",
    }
    return descriptions.get(name, f"Ejecuta la tool controlada {name}.")


def _schema_for(model: type[BaseModel]) -> dict:
    if model is BaseModel:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    return model.model_json_schema()


def _parse_arguments(tool: str, arguments: dict) -> BaseModel:
    model = TOOL_ARGUMENTS[tool]
    try:
        if model is BaseModel:
            return model()
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()
        ) from None


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
        return bool(
            context.budget_session.can_see_amounts
            and (policy_allows_prices(context.policy) or context.access_scope.can_view_prices)
        )
    return bool(policy_allows_prices(context.policy) or context.access_scope.can_view_prices)


def _allows_budget_search(context: IntegrationContext) -> bool:
    return bool(
        policy_allows_budget_search(context.policy) or context.access_scope.can_search_budgets
    )


def _average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _model_dict(item) -> dict:
    data = {}
    for column in item.__table__.columns:
        value = getattr(item, column.name)
        data[column.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return data


def _document_source(
    db: Session,
    document: Document,
    context: IntegrationContext,
    *,
    confidence: float | None = None,
) -> IntegrationSource:
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number.asc())
        .limit(1)
    )
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


# ---------------------------------------------------------------------------
# Context-aware filtering helpers
# ---------------------------------------------------------------------------


def _filter_budgets_for_context(db: Session, budgets, context: IntegrationContext) -> list[Budget]:
    return _filter_records_for_context(db, budgets, context)


def _filter_records_for_context(db: Session, records, context: IntegrationContext) -> list:
    records_list = list(records)
    if not context.budget_session:
        return filter_records_by_document_scope(db, records_list, context.access_scope)
    allowed_document_ids = _filter_document_ids_for_context(
        db, [record.document_id for record in records_list], context
    )
    return [record for record in records_list if record.document_id in allowed_document_ids]


def _filter_search_results_for_context(db: Session, results, context: IntegrationContext) -> list:
    results_list = list(results)
    if not context.budget_session:
        return filter_search_results_for_scope(db, results_list, context.access_scope)
    allowed_document_ids = _filter_document_ids_for_context(
        db, [result.document_id for result in results_list], context
    )
    return [result for result in results_list if result.document_id in allowed_document_ids]


def _search_filters_for_context(context: IntegrationContext, filters: dict | None) -> dict:
    scoped_filters = dict(filters or {})
    if context.budget_session:
        scoped_filters["budget_scope_id"] = context.budget_session.budget_scope_id
        scoped_filters["_cache_scope"] = (
            f"budget:{context.budget_session.budget_scope_id}:client:{context.client.id}"
        )
    return scoped_filters


def _filter_document_ids_for_context(
    db: Session, document_ids, context: IntegrationContext
) -> set[int]:
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
    allowed = {int(row[0]) for row in rows}
    if not context.access_scope.denied_tags:
        return allowed
    filtered: set[int] = set()
    for document_id in allowed:
        metadata = get_document_access_metadata(db, document_id)
        tags = {
            str(tag).strip().lower()
            for tag in (metadata.tags_json if metadata else [])
            if str(tag).strip()
        }
        if not (tags & context.access_scope.denied_tags):
            filtered.add(document_id)
    return filtered


def _document_id_allowed_for_context(
    db: Session, document_id: int | None, context: IntegrationContext
) -> bool:
    if document_id is None:
        return False
    return int(document_id) in _filter_document_ids_for_context(db, [document_id], context)


def _can_access_document_for_context(
    db: Session, document: Document | None, context: IntegrationContext
) -> bool:
    if not context.budget_session:
        return can_access_document(db, document, context.access_scope)
    if not document or document.deleted_at is not None:
        return False
    return document.id in _filter_document_ids_for_context(db, [document.id], context)


def _can_access_plan(db: Session, plan_id: int, context: IntegrationContext) -> bool:
    from app.models import Plan

    plan = db.get(Plan, plan_id)
    if not plan:
        return False
    return _document_id_allowed_for_context(db, plan.document_id, context)
