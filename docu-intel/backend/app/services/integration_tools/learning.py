from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ClassificationSuggestion, Document
from app.schemas.integration import IntegrationToolExecuteResponse
from app.services.audit import write_audit
from app.services.integration_tools.common import (
    GetImprovementCandidatesArgs,
    ProposeClassificationCorrectionArgs,
    ProposeClassificationRuleArgs,
    ProposeEntityLinkArgs,
    SubmitQualityFeedbackArgs,
    _can_access_document_for_context,
    _filter_document_ids_for_context,
    _response,
)
from app.services.integration_security import IntegrationContext

logger = logging.getLogger(__name__)


def _handle_duplicate_suggestion(
    db: Session,
    request_id: str,
    tool_name: str,
    context: IntegrationContext,
    suggestion: ClassificationSuggestion,
) -> IntegrationToolExecuteResponse:
    """Rollback y devuelve respuesta 409 si la sugerencia ya existe."""
    db.rollback()
    existing = db.scalars(
        select(ClassificationSuggestion).where(
            ClassificationSuggestion.document_id == suggestion.document_id,
            ClassificationSuggestion.suggestion_type == suggestion.suggestion_type,
            ClassificationSuggestion.status.in_(["pending", "approved"]),
        )
    ).first()
    return _response(
        request_id,
        tool_name,
        context,
        data={
            "status": "duplicate",
            "document_id": suggestion.document_id,
            "existing_suggestion_id": existing.id if existing else None,
        },
        warnings=[
            "Ya existe una sugerencia pendiente o aprobada del mismo tipo para este documento."
        ],
    )


def _safe_commit(
    db: Session,
    suggestion: ClassificationSuggestion,
    request_id: str,
    tool_name: str,
    context: IntegrationContext,
) -> ClassificationSuggestion | IntegrationToolExecuteResponse:
    """Commit con manejo de IntegrityError (duplicado)."""
    try:
        db.commit()
        db.refresh(suggestion)
        return suggestion
    except IntegrityError:
        return _handle_duplicate_suggestion(db, request_id, tool_name, context, suggestion)


def execute_propose_classification_correction(
    db: Session,
    context: IntegrationContext,
    args: ProposeClassificationCorrectionArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    """El agente externo sugiere cambiar document_type de un documento."""
    document = db.get(Document, args.document_id)
    if not _can_access_document_for_context(db, document, context):
        return _response(
            request_id,
            "propose_classification_correction",
            context,
            data={"status": "not_found", "document_id": args.document_id},
            warnings=["Documento no encontrado o sin acceso."],
        )

    suggestion = ClassificationSuggestion(
        document_id=args.document_id,
        integration_client_id=context.client.id if context.client else None,
        suggestion_type="classification_correction",
        suggested_document_type=args.suggested_document_type,
        current_document_type=document.document_type if document else None,
        confidence=args.confidence,
        reason=args.reason,
        evidence_json=args.evidence,
        status="pending",
    )
    db.add(suggestion)
    db.flush()

    write_audit(
        db,
        user=None,
        action="integration_propose_classification_correction",
        entity_type="classification_suggestion",
        entity_id=suggestion.id,
        details={
            "document_id": args.document_id,
            "suggested_document_type": args.suggested_document_type,
            "current_document_type": document.document_type if document else None,
            "confidence": args.confidence,
        },
    )
    result = _safe_commit(db, suggestion, request_id, "propose_classification_correction", context)
    if not isinstance(result, ClassificationSuggestion):
        return result

    return _response(
        request_id,
        "propose_classification_correction",
        context,
        data={
            "status": "pending",
            "suggestion_id": suggestion.id,
            "document_id": args.document_id,
            "suggested_document_type": args.suggested_document_type,
        },
    )


def execute_propose_entity_link(
    db: Session,
    context: IntegrationContext,
    args: ProposeEntityLinkArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    """El agente externo sugiere vincular dos documentos (ej. presupuesto<>pedido)."""
    source_doc = db.get(Document, args.source_document_id)
    target_doc = db.get(Document, args.target_document_id)
    if not _can_access_document_for_context(db, source_doc, context):
        return _response(
            request_id,
            "propose_entity_link",
            context,
            data={"status": "not_found", "source_document_id": args.source_document_id},
            warnings=["Documento origen no encontrado o sin acceso."],
        )
    if not _can_access_document_for_context(db, target_doc, context):
        return _response(
            request_id,
            "propose_entity_link",
            context,
            data={"status": "not_found", "target_document_id": args.target_document_id},
            warnings=["Documento destino no encontrado o sin acceso."],
        )

    suggestion = ClassificationSuggestion(
        document_id=args.source_document_id,
        target_document_id=args.target_document_id,
        integration_client_id=context.client.id if context.client else None,
        suggestion_type="entity_link",
        target_action=args.target_action,
        confidence=args.confidence,
        reason=args.reason,
        status="pending",
    )
    db.add(suggestion)
    db.flush()

    write_audit(
        db,
        user=None,
        action="integration_propose_entity_link",
        entity_type="classification_suggestion",
        entity_id=suggestion.id,
        details={
            "source_document_id": args.source_document_id,
            "target_document_id": args.target_document_id,
            "target_action": args.target_action,
            "confidence": args.confidence,
        },
    )
    result = _safe_commit(db, suggestion, request_id, "propose_entity_link", context)
    if not isinstance(result, ClassificationSuggestion):
        return result

    return _response(
        request_id,
        "propose_entity_link",
        context,
        data={
            "status": "pending",
            "suggestion_id": suggestion.id,
            "source_document_id": args.source_document_id,
            "target_document_id": args.target_document_id,
        },
    )


def execute_propose_classification_rule(
    db: Session,
    context: IntegrationContext,
    args: ProposeClassificationRuleArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    """El agente externo propone una nueva regla de clasificacion (keyword/regex)."""
    evidence_doc_id = args.evidence_document_id
    if evidence_doc_id is None:
        return _response(
            request_id,
            "propose_classification_rule",
            context,
            data={"status": "invalid", "reason": "evidence_document_id is required"},
            warnings=["Las reglas de clasificacion requieren un documento de evidencia concreto."],
        )
    evidence_doc = db.get(Document, evidence_doc_id)
    if not _can_access_document_for_context(db, evidence_doc, context):
        return _response(
            request_id,
            "propose_classification_rule",
            context,
            data={"status": "not_found", "evidence_document_id": evidence_doc_id},
            warnings=["Documento de evidencia no encontrado o sin acceso."],
        )

    suggestion = ClassificationSuggestion(
        document_id=evidence_doc_id,
        integration_client_id=context.client.id if context.client else None,
        suggestion_type="classification_rule",
        pattern_value=args.pattern_value,
        target_class=args.target_class,
        target_action=args.target_action,
        confidence=args.confidence,
        reason=args.reason,
        evidence_json={"evidence_document_id": evidence_doc_id},
        status="pending",
    )
    db.add(suggestion)
    db.flush()

    write_audit(
        db,
        user=None,
        action="integration_propose_classification_rule",
        entity_type="classification_suggestion",
        entity_id=suggestion.id,
        details={
            "pattern_value": args.pattern_value,
            "target_class": args.target_class,
            "target_action": args.target_action,
            "evidence_document_id": evidence_doc_id,
            "confidence": args.confidence,
        },
    )
    result = _safe_commit(db, suggestion, request_id, "propose_classification_rule", context)
    if not isinstance(result, ClassificationSuggestion):
        return result

    return _response(
        request_id,
        "propose_classification_rule",
        context,
        data={
            "status": "pending",
            "suggestion_id": suggestion.id,
            "pattern_value": args.pattern_value,
            "target_class": args.target_class,
        },
    )


def execute_submit_quality_feedback(
    db: Session,
    context: IntegrationContext,
    args: SubmitQualityFeedbackArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    """El agente externo da feedback estructurado sobre un campo extraido."""
    document = db.get(Document, args.document_id)
    if not _can_access_document_for_context(db, document, context):
        return _response(
            request_id,
            "submit_quality_feedback",
            context,
            data={"status": "not_found", "document_id": args.document_id},
            warnings=["Documento no encontrado o sin acceso."],
        )

    suggestion = ClassificationSuggestion(
        document_id=args.document_id,
        integration_client_id=context.client.id if context.client else None,
        suggestion_type="quality_feedback",
        confidence=args.confidence,
        reason=args.reason,
        evidence_json={
            "field": args.field,
            "old_value": args.old_value,
            "suggested_value": args.suggested_value,
        },
        status="pending",
    )
    db.add(suggestion)
    db.flush()

    write_audit(
        db,
        user=None,
        action="integration_submit_quality_feedback",
        entity_type="classification_suggestion",
        entity_id=suggestion.id,
        details={
            "document_id": args.document_id,
            "field": args.field,
            "old_value": args.old_value,
            "suggested_value": args.suggested_value,
            "confidence": args.confidence,
        },
    )
    result = _safe_commit(db, suggestion, request_id, "submit_quality_feedback", context)
    if not isinstance(result, ClassificationSuggestion):
        return result

    return _response(
        request_id,
        "submit_quality_feedback",
        context,
        data={
            "status": "pending",
            "suggestion_id": suggestion.id,
            "document_id": args.document_id,
            "field": args.field,
        },
    )


def execute_get_improvement_candidates(
    db: Session,
    context: IntegrationContext,
    args: GetImprovementCandidatesArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    """Devuelve documentos con baja confianza o que necesitan revision humana."""
    from app.schemas.learning import ImprovementCandidate

    low_confidence_statuses = {"needs_human_review", "processed_low_quality"}

    query = select(Document).where(Document.deleted_at.is_(None))

    if context.budget_session:
        query = query.where(Document.budget_scope_id == context.budget_session.budget_scope_id)

    query = query.order_by(Document.confidence.asc().nulls_last()).limit(args.limit * 2)

    documents = list(db.scalars(query).all())
    allowed_ids = _filter_document_ids_for_context(db, [doc.id for doc in documents], context)

    candidates = []
    for doc in documents:
        if doc.id not in allowed_ids:
            continue
        is_low_confidence = doc.confidence is not None and doc.confidence < args.min_confidence
        is_review_needed = doc.quality_status in low_confidence_statuses

        if is_low_confidence or is_review_needed:
            reason_parts = []
            if is_low_confidence:
                reason_parts.append(f"confianza baja ({doc.confidence:.2f} < {args.min_confidence})")
            if is_review_needed:
                reason_parts.append(f"estado de calidad: {doc.quality_status}")

            candidates.append(
                ImprovementCandidate(
                    document_id=doc.id,
                    filename=doc.original_filename,
                    document_type=doc.document_type,
                    current_status=doc.quality_status,
                    reason="; ".join(reason_parts),
                    confidence=doc.confidence,
                )
            )
        if len(candidates) >= args.limit:
            break

    return _response(
        request_id,
        "get_improvement_candidates",
        context,
        data=[c.model_dump(mode="json") for c in candidates],
    )