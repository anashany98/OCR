from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models import Document, ExtractionJob
from app.schemas.integration import (
    IntegrationDocumentStatus,
    IntegrationJobStatus,
    IntegrationManifest,
    IntegrationSessionCreateRequest,
    IntegrationSessionCreateResponse,
    IntegrationToolExecuteRequest,
    IntegrationToolExecuteResponse,
    IntegrationUploadResponse,
)
from app.services.audit import write_audit
from app.services.budget_scope import (
    assign_document_budget_scope,
    create_budget_session_token,
    get_budget_scope_by_code,
    get_client_budget_permission,
)
from app.services.document_service import register_upload
from app.services.integration_security import IntegrationContext, get_integration_context, require_scope
from app.services.integration_tools import build_manifest, execute_integration_tool
from app.services.tenant_access import can_access_document, get_document_access_metadata
from app.services.webhooks import build_webhook_test_payload, emit_integration_webhook

router = APIRouter()


@router.get("/manifest", response_model=IntegrationManifest)
def manifest(
    context: IntegrationContext = Depends(get_integration_context),
) -> IntegrationManifest:
    require_scope(context, "read")
    return build_manifest()


@router.post("/sessions", response_model=IntegrationSessionCreateResponse)
def create_budget_session(
    payload: IntegrationSessionCreateRequest,
    db: Session = Depends(get_db),
    context: IntegrationContext = Depends(get_integration_context),
) -> IntegrationSessionCreateResponse:
    require_scope(context, "read")
    scope = get_budget_scope_by_code(db, payload.budget_code)
    if not scope:
        raise HTTPException(status_code=404, detail="Budget scope not found")
    permission = get_client_budget_permission(db, client_id=context.client.id, budget_scope_id=scope.id)
    if not permission or not permission.can_query:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Integration client cannot query this budget scope")
    can_see_amounts = bool(permission.can_see_amounts)
    token = create_budget_session_token(
        client_id=context.client.id,
        technician_id=context.technician_id,
        budget_scope_id=scope.id,
        budget_code=scope.budget_code,
        can_see_amounts=can_see_amounts,
    )
    write_audit(
        db,
        user=None,
        action="integration_budget_session_created",
        entity_type="budget_scope",
        entity_id=scope.id,
        details={
            "integration_client": context.client.name,
            "technician_id": context.technician_id,
            "technician_name": context.technician_name,
            "budget_code": scope.budget_code,
            "can_see_amounts": can_see_amounts,
        },
    )
    db.commit()
    return IntegrationSessionCreateResponse(
        session_token=token,
        budget_code=scope.budget_code,
        budget_scope_id=scope.id,
        expires_in=settings.integration_session_expire_seconds,
        can_see_amounts=can_see_amounts,
    )


@router.post("/tools/execute", response_model=IntegrationToolExecuteResponse)
def execute_tool(
    payload: IntegrationToolExecuteRequest,
    db: Session = Depends(get_db),
    context: IntegrationContext = Depends(get_integration_context),
) -> IntegrationToolExecuteResponse:
    require_scope(context, "read")
    response = execute_integration_tool(db, context=context, tool=payload.tool, arguments=payload.arguments)
    if payload.sandbox:
        response.warnings.append("Sandbox activo: resultado de prueba para validar fuentes, scope y redacciones.")
    write_audit(
        db,
        user=None,
        action="integration_tool_sandbox" if payload.sandbox else "integration_tool_execute",
        entity_type="integration_client",
        entity_id=context.client.id,
        details={
            "request_id": response.request_id,
            "integration_client": context.client.name,
            "technician_id": context.technician_id,
            "technician_name": context.technician_name,
            "policy": context.policy.name,
            "tool": payload.tool,
            "arguments": _safe_arguments(payload.arguments),
            "sandbox": payload.sandbox,
            "sources_count": len(response.sources),
            "redactions": response.redactions,
            "scope": response.scope,
        },
    )
    db.commit()
    return response


@router.post("/documents/upload", response_model=IntegrationUploadResponse)
def upload_document(
    budget_code: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    context: IntegrationContext = Depends(get_integration_context),
) -> IntegrationUploadResponse:
    require_scope(context, "upload")
    document, job = register_upload(
        db,
        filename=file.filename or "uploaded_document",
        stream=file.file,
        user=None,
        source_path=f"integration:{context.client.name}:{context.technician_id}",
        enqueue=settings.integration_enqueue_uploads,
    )
    if budget_code:
        assign_document_budget_scope(db, document, budget_code=budget_code)
    write_audit(
        db,
        user=None,
        action="integration_document_upload",
        entity_type="document",
        entity_id=document.id,
        details={
            "integration_client": context.client.name,
            "technician_id": context.technician_id,
            "technician_name": context.technician_name,
            "policy": context.policy.name,
            "filename": document.original_filename,
            "job_id": job.id if job else None,
        },
    )
    db.commit()
    db.refresh(document)
    if job:
        db.refresh(job)
    return IntegrationUploadResponse(document=document, job=job)


@router.get("/documents/{document_id}/status", response_model=IntegrationDocumentStatus)
def document_status(
    document_id: int,
    db: Session = Depends(get_db),
    context: IntegrationContext = Depends(get_integration_context),
) -> Document:
    require_scope(context, "read")
    document = db.get(Document, document_id)
    if not _can_access_integration_document(db, document, context):
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/jobs/{job_id}", response_model=IntegrationJobStatus)
def job_status(
    job_id: int,
    db: Session = Depends(get_db),
    context: IntegrationContext = Depends(get_integration_context),
) -> ExtractionJob:
    require_scope(context, "read")
    job = db.get(ExtractionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    document = db.get(Document, job.document_id)
    if not _can_access_integration_document(db, document, context):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/webhooks/test")
def test_webhook(
    context: IntegrationContext = Depends(get_integration_context),
) -> dict:
    require_scope(context, "admin")
    payload = build_webhook_test_payload()
    result = emit_integration_webhook(payload["event"], payload["payload"])
    return {"webhook": result, "payload": payload}


def _safe_arguments(arguments: dict) -> dict:
    safe = {}
    for key, value in arguments.items():
        if "key" in key.lower() or "password" in key.lower() or "secret" in key.lower():
            safe[key] = "[REDACTED]"
        else:
            safe[key] = value
    return safe


def _can_access_integration_document(db: Session, document: Document | None, context: IntegrationContext) -> bool:
    if context.budget_session:
        if not document or document.deleted_at is not None or document.budget_scope_id != context.budget_session.budget_scope_id:
            return False
        metadata = get_document_access_metadata(db, document.id)
        tags = {str(tag).strip().lower() for tag in (metadata.tags_json if metadata else []) if str(tag).strip()}
        return not bool(tags & context.access_scope.denied_tags)
    return can_access_document(db, document, context.access_scope)
