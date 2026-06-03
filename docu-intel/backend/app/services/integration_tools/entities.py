from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.integration import IntegrationToolExecuteResponse
from app.services.integration_tools.common import (
    EntitySearchArgs,
    _filter_document_ids_for_context,
    _model_dict,
    _response,
)
from app.services.integration_security import IntegrationContext
from app.tools import internal


def execute_search_entities(
    db: Session,
    context: IntegrationContext,
    args: EntitySearchArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    entities = internal.search_entities(db, args.entity_type, args.value)
    allowed_document_ids = _filter_document_ids_for_context(db, [entity.document_id for entity in entities], context)
    entities = [entity for entity in entities if entity.document_id in allowed_document_ids]
    return _response(request_id, "search_entities", context, data=[_model_dict(entity) for entity in entities])
