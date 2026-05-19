import secrets
import shutil
import csv
import fnmatch
import io
import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import settings
from app.database.session import get_db
from app.models import (
    AccessGroup,
    AccessGroupMember,
    ApiClientBudgetScope,
    AuditLog,
    Budget,
    BudgetScope,
    Document,
    DocumentAccessMetadata,
    DocumentPage,
    ExtractionJob,
    FolderAssignmentRule,
    Hotel,
    HotelChain,
    IngestionEvent,
    IntegrationClient,
    Order,
    Plan,
    SensitiveTag,
    User,
    WatchedFile,
)
from app.schemas.admin import (
    AdminAlertRead,
    AdminStats,
    ApiClientBudgetScopeRead,
    ApiClientBudgetScopeUpsert,
    AuditLogRead,
    BudgetScopeCreate,
    BudgetScopeRead,
    BulkTagsRequest,
    BulkTagsResponse,
    IntegrationClientCreate,
    IntegrationClientRead,
    IntegrationClientSecretRead,
    IntegrationClientUpdate,
    IntegrationSandboxExecuteRequest,
    JobActionResponse,
    OcrReviewPageRead,
    OcrReviewPageUpdate,
    EffectiveAccessRead,
    PaginatedDocumentsResponse,
    ProcessingMetricsRead,
    ProductionChecklistItem,
    ProductionChecklistResponse,
    ProductionReadinessResponse,
    QualityRecalculateRequest,
    QualityRecalculateResponse,
    QualityRulesRead,
    QualitySummaryRead,
    QueueStatusRead,
    RedactionPreviewRequest,
    RedactionPreviewResponse,
    RulePreviewRequest,
    RulePreviewResponse,
    SystemHealthRead,
    StorageIntegrityResponse,
    WorkInboxActionRequest,
    WorkInboxActionResponse,
    WorkInboxItemRead,
)
from app.schemas.documents import DocumentRead
from app.schemas.tenant import (
    AccessGroupCreate,
    AccessGroupMemberRead,
    AccessGroupMemberUpsert,
    AccessGroupRead,
    AccessGroupUpdate,
    DocumentAccessRead,
    DocumentAccessUpdate,
    FolderRuleCreate,
    FolderRuleRead,
    FolderRulesApplyRequest,
    FolderRulesApplyResponse,
    FolderRuleUpdate,
    HotelChainCreate,
    HotelChainRead,
    HotelChainUpdate,
    HotelCreate,
    HotelRead,
    HotelUpdate,
    SensitiveTagCreate,
    SensitiveTagRead,
    SensitiveTagUpdate,
)
from app.services.audit import write_audit
from app.services.access_explain import explain_document_access
from app.services.access_review import effective_access_payload
from app.services.access_policy import policy_allows_prices, resolve_access_policy
from app.services.budget_scope import ensure_budget_scope
from app.services.cache import cache_service
from app.services.data_quality import quality_rules_payload, quality_summary, recalculate_quality
from app.services.document_graph import build_document_graph
from app.services.document_service import reprocess_document
from app.services.integration_security import IntegrationContext, hash_integration_api_key
from app.services.integration_tools import execute_integration_tool
from app.services.maintenance import build_maintenance_report, build_operations_overview, build_operations_status
from app.services.operations import build_admin_alerts, build_processing_metrics
from app.services.production_readiness import production_readiness, storage_integrity
from app.services.quality import refresh_quality_from_existing_pages
from app.services.queue_control import build_queue_control_status, cancel_pending_job, pause_ingestion, resume_ingestion
from app.services.redaction import redact_sensitive_text
from app.services.tenant_access import (
    apply_folder_rules_to_all_documents,
    ensure_document_access_metadata,
    filter_documents_for_scope,
    resolve_technician_access_scope,
    resolve_user_access_scope,
)

router = APIRouter()


@router.get("/stats", response_model=AdminStats)
def stats(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))) -> AdminStats:
    def count_where(*criteria) -> int:
        stmt = select(func.count()).select_from(Document).where(Document.deleted_at.is_(None), *criteria)
        return int(db.scalar(stmt) or 0)

    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    accepted_without_order = int(
        db.scalar(
            select(func.count())
            .select_from(Budget)
            .where(Budget.accepted_detected.is_(True))
            .where(Budget.id.not_in(ordered_budget_ids))
        )
        or 0
    )
    plans_without_scale = int(db.scalar(select(func.count()).select_from(Plan).where(Plan.has_valid_scale.is_(False))) or 0)
    return AdminStats(
        documents_total=count_where(),
        documents_processed=count_where(Document.status == "processed"),
        documents_pending=count_where(Document.status == "pending"),
        documents_failed=count_where(Document.status == "failed"),
        documents_needs_review=count_where(Document.status == "needs_review"),
        duplicates=count_where(Document.status == "duplicate"),
        ocr_errors=count_where(Document.status == "failed"),
        accepted_budgets_without_order=accepted_without_order,
        plans_without_valid_scale=plans_without_scale,
    )


@router.get("/alerts", response_model=list[AdminAlertRead])
def alerts(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))) -> list:
    return build_admin_alerts(db)


@router.get("/processing-metrics", response_model=ProcessingMetricsRead)
def processing_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_processing_metrics(db)


@router.get("/system/metrics", response_model=ProcessingMetricsRead)
def system_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_processing_metrics(db)


@router.get("/system/health", response_model=SystemHealthRead)
def system_health(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    checks = {
        "database": _database_health(db),
        "redis": _redis_health(),
        "disk_files": _disk_health(settings.files_dir),
        "disk_input": _disk_health(settings.input_dir),
        "watcher": _watcher_health(db),
        "queues": _queue_health(db),
    }
    status = "ok" if all(item["status"] == "ok" for item in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@router.get("/queues", response_model=QueueStatusRead)
def queues(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> QueueStatusRead:
    return QueueStatusRead(**build_queue_control_status(db).__dict__)


@router.post("/queues/pause", response_model=QueueStatusRead)
def pause_queues(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> QueueStatusRead:
    pause_ingestion()
    write_audit(db, user=user, action="ingestion_paused", entity_type="operations")
    db.commit()
    return QueueStatusRead(**build_queue_control_status(db).__dict__)


@router.post("/queues/resume", response_model=QueueStatusRead)
def resume_queues(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> QueueStatusRead:
    resume_ingestion()
    write_audit(db, user=user, action="ingestion_resumed", entity_type="operations")
    db.commit()
    return QueueStatusRead(**build_queue_control_status(db).__dict__)


@router.post("/jobs/{job_id}/retry", response_model=JobActionResponse)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ExtractionJob:
    job = _get_or_404(db, ExtractionJob, job_id, "Job not found")
    document = _get_or_404(db, Document, job.document_id, "Document not found")
    new_job = reprocess_document(db, document=document, user=user, job_type=job.job_type)
    write_audit(
        db,
        user=user,
        action="job_retry_requested",
        entity_type="extraction_job",
        entity_id=job.id,
        details={"new_job_id": new_job.id, "document_id": document.id},
    )
    db.commit()
    db.refresh(new_job)
    return new_job


@router.post("/jobs/{job_id}/cancel", response_model=JobActionResponse)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ExtractionJob:
    job = _get_or_404(db, ExtractionJob, job_id, "Job not found")
    try:
        cancel_pending_job(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(db, user=user, action="job_cancelled", entity_type="extraction_job", entity_id=job.id)
    db.commit()
    db.refresh(job)
    return job


@router.get("/budget-scopes", response_model=list[BudgetScopeRead])
def list_budget_scopes(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[BudgetScope]:
    stmt = select(BudgetScope).order_by(BudgetScope.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where((BudgetScope.budget_code.ilike(pattern)) | (BudgetScope.display_name.ilike(pattern)))
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


@router.post("/budget-scopes", response_model=BudgetScopeRead)
def create_budget_scope(
    payload: BudgetScopeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> BudgetScope:
    scope = ensure_budget_scope(db, payload.budget_code, source_path=payload.source_path)
    scope.local_path = payload.local_path
    scope.display_name = payload.display_name or scope.display_name
    scope.status = payload.status
    write_audit(db, user=user, action="budget_scope_upserted", entity_type="budget_scope", entity_id=scope.id)
    db.commit()
    db.refresh(scope)
    return scope


@router.get("/budget-scopes/{scope_id}/client-permissions", response_model=list[ApiClientBudgetScopeRead])
def list_budget_scope_client_permissions(
    scope_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
) -> list[ApiClientBudgetScope]:
    _get_or_404(db, BudgetScope, scope_id, "Budget scope not found")
    return list(
        db.scalars(
            select(ApiClientBudgetScope)
            .where(ApiClientBudgetScope.budget_scope_id == scope_id)
            .order_by(ApiClientBudgetScope.id.asc())
        ).all()
    )


@router.post("/budget-scopes/{scope_id}/client-permissions", response_model=ApiClientBudgetScopeRead)
def upsert_budget_scope_client_permission(
    scope_id: int,
    payload: ApiClientBudgetScopeUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> ApiClientBudgetScope:
    _get_or_404(db, BudgetScope, scope_id, "Budget scope not found")
    _get_or_404(db, IntegrationClient, payload.client_id, "Integration client not found")
    permission = db.scalar(
        select(ApiClientBudgetScope)
        .where(ApiClientBudgetScope.budget_scope_id == scope_id)
        .where(ApiClientBudgetScope.api_client_id == payload.client_id)
    )
    if not permission:
        permission = ApiClientBudgetScope(api_client_id=payload.client_id, budget_scope_id=scope_id)
        db.add(permission)
        db.flush()
    permission.can_query = payload.can_query
    permission.can_see_amounts = payload.can_see_amounts
    write_audit(
        db,
        user=user,
        action="budget_scope_client_permission_upserted",
        entity_type="budget_scope",
        entity_id=scope_id,
        details={
            "api_client_id": payload.client_id,
            "can_query": payload.can_query,
            "can_see_amounts": payload.can_see_amounts,
        },
    )
    db.commit()
    db.refresh(permission)
    return permission


@router.get("/integration-clients", response_model=list[IntegrationClientRead])
def list_integration_clients(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
) -> list[IntegrationClient]:
    return list(db.scalars(select(IntegrationClient).order_by(IntegrationClient.name.asc())).all())


@router.post("/integration-clients", response_model=IntegrationClientSecretRead)
def create_integration_client(
    payload: IntegrationClientCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> IntegrationClientSecretRead:
    existing = db.scalar(select(IntegrationClient).where(IntegrationClient.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Integration client name already exists")
    api_key = _new_api_key()
    client = IntegrationClient(
        name=payload.name,
        api_key_hash=hash_integration_api_key(api_key),
        scopes_json=_normalize_scopes(payload.scopes),
        is_active=payload.is_active,
    )
    db.add(client)
    db.flush()
    write_audit(
        db,
        user=user,
        action="integration_client_created",
        entity_type="integration_client",
        entity_id=client.id,
        details={"name": client.name, "scopes": client.scopes_json},
    )
    db.commit()
    db.refresh(client)
    return IntegrationClientSecretRead.model_validate(client, from_attributes=True).model_copy(update={"api_key": api_key})


@router.patch("/integration-clients/{client_id}", response_model=IntegrationClientRead)
def update_integration_client(
    client_id: int,
    payload: IntegrationClientUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> IntegrationClient:
    client = _get_or_404(db, IntegrationClient, client_id, "Integration client not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != client.name:
        existing = db.scalar(select(IntegrationClient).where(IntegrationClient.name == data["name"]))
        if existing:
            raise HTTPException(status_code=409, detail="Integration client name already exists")
        client.name = data["name"]
    if "scopes" in data and data["scopes"] is not None:
        client.scopes_json = _normalize_scopes(data["scopes"])
    if "is_active" in data and data["is_active"] is not None:
        client.is_active = bool(data["is_active"])
    write_audit(
        db,
        user=user,
        action="integration_client_updated",
        entity_type="integration_client",
        entity_id=client.id,
        details={"name": client.name, "scopes": client.scopes_json, "is_active": client.is_active},
    )
    db.commit()
    db.refresh(client)
    return client


@router.post("/integration-clients/{client_id}/rotate-key", response_model=IntegrationClientSecretRead)
def rotate_integration_client_key(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> IntegrationClientSecretRead:
    client = _get_or_404(db, IntegrationClient, client_id, "Integration client not found")
    api_key = _new_api_key()
    client.api_key_hash = hash_integration_api_key(api_key)
    write_audit(
        db,
        user=user,
        action="integration_client_key_rotated",
        entity_type="integration_client",
        entity_id=client.id,
        details={"name": client.name},
    )
    db.commit()
    db.refresh(client)
    return IntegrationClientSecretRead.model_validate(client, from_attributes=True).model_copy(update={"api_key": api_key})


@router.get("/operations-status")
def operations_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_operations_status(db)


@router.get("/operations/overview")
def operations_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_operations_overview(db)


@router.get("/operations/documents", response_model=PaginatedDocumentsResponse)
def operations_documents(
    status: str | None = None,
    document_type: str | None = None,
    q: str | None = None,
    quality_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    scope = resolve_user_access_scope(db, user)
    stmt = select(Document).where(Document.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
    criteria = []
    if status:
        criteria.append(Document.status == status)
    if document_type:
        criteria.append(Document.document_type == document_type)
    if quality_status:
        criteria.append(Document.quality_status == quality_status)
    if q:
        criteria.append(Document.original_filename.ilike(f"%{q}%"))
    if criteria:
        stmt = stmt.where(*criteria)
        count_stmt = count_stmt.where(*criteria)
    stmt = stmt.order_by(Document.created_at.desc())
    if scope.is_admin:
        documents = list(db.scalars(stmt.offset(offset).limit(limit)).all())
        total = int(db.scalar(count_stmt) or 0)
    else:
        candidates = list(db.scalars(stmt.limit(max(limit + offset, 1000))).all())
        visible = filter_documents_for_scope(db, candidates, scope)
        total = len(visible)
        documents = visible[offset : offset + limit]
    return {
        "items": [_document_operation_payload(document) for document in documents],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/maintenance-report")
def maintenance_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_maintenance_report(db)


@router.get("/work-inbox", response_model=list[WorkInboxItemRead])
def work_inbox(
    max_ocr_confidence: float = Query(default=0.70, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[WorkInboxItemRead]:
    items: list[WorkInboxItemRead] = []

    low_ocr_rows = db.execute(
        select(DocumentPage, Document)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentPage.ocr_confidence.is_not(None))
        .where(DocumentPage.ocr_confidence < max_ocr_confidence)
        .where(DocumentPage.review_status != "approved")
        .order_by(DocumentPage.ocr_confidence.asc(), Document.created_at.desc())
        .limit(limit)
    ).all()
    for page, document in low_ocr_rows:
        items.append(
            WorkInboxItemRead(
                kind="low_ocr",
                severity="warning",
                title="OCR de baja confianza",
                description=f"{document.original_filename}, pagina {page.page_number}: {page.ocr_confidence or 0:.0%}",
                document_id=document.id,
                page_id=page.id,
                action_url=f"/ocr-review?document={document.id}&page={page.id}",
                status=page.review_status,
                created_at=page.created_at,
            )
        )

    for document in db.scalars(
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(Document.document_type == "desconocido")
        .order_by(Document.created_at.desc())
        .limit(limit)
    ).all():
        items.append(
            WorkInboxItemRead(
                kind="unknown_type",
                severity="warning",
                title="Documento sin clasificar",
                description=document.original_filename,
                document_id=document.id,
                action_url=f"/documents/{document.id}",
                status=document.status,
                created_at=document.created_at,
            )
        )

    for document in db.scalars(
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(Document.status == "duplicate")
        .order_by(Document.created_at.desc())
        .limit(limit)
    ).all():
        items.append(
            WorkInboxItemRead(
                kind="duplicate",
                severity="info",
                title="Documento duplicado",
                description=document.original_filename,
                document_id=document.id,
                action_url=f"/documents/{document.id}",
                status=document.status,
                created_at=document.created_at,
            )
        )

    failed_jobs = db.execute(
        select(ExtractionJob, Document)
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(Document.deleted_at.is_(None))
        .where(ExtractionJob.status == "failed")
        .order_by(ExtractionJob.finished_at.desc().nullslast(), Document.created_at.desc())
        .limit(limit)
    ).all()
    for job, document in failed_jobs:
        items.append(
            WorkInboxItemRead(
                kind="failed_job",
                severity="error",
                title="Job fallido",
                description=job.error_message or document.original_filename,
                document_id=document.id,
                job_id=job.id,
                action_url=f"/jobs?job={job.id}",
                status=job.status,
                created_at=job.finished_at or document.created_at,
            )
        )

    for document in db.scalars(
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(Document.quality_status.in_(["processed_missing_fields", "needs_human_review", "processed_low_quality"]))
        .order_by(Document.created_at.desc())
        .limit(limit)
    ).all():
        items.append(
            WorkInboxItemRead(
                kind="missing_fields" if document.quality_status == "processed_missing_fields" else document.quality_status,
                severity="warning",
                title="Documento requiere revision",
                description=f"{document.original_filename}: {document.quality_status}",
                document_id=document.id,
                action_url=f"/documents/{document.id}",
                status=document.status,
                created_at=document.created_at,
            )
        )

    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    accepted_budgets = db.scalars(
        select(Budget)
        .join(Document, Document.id == Budget.document_id)
        .where(Document.deleted_at.is_(None))
        .where(or_(Budget.accepted_detected.is_(True), Budget.status.in_(["aceptado", "aprobado", "accepted"])))
        .where(Budget.id.not_in(ordered_budget_ids))
        .order_by(Budget.created_at.desc())
        .limit(limit)
    ).all()
    for budget in accepted_budgets:
        items.append(
            WorkInboxItemRead(
                kind="accepted_budget_without_order",
                severity="warning",
                title="Presupuesto aceptado sin pedido",
                description=budget.budget_number or f"Presupuesto #{budget.id}",
                document_id=budget.document_id,
                action_url=f"/budgets/{budget.id}",
                status=budget.status,
                created_at=budget.created_at,
            )
        )

    items.sort(key=lambda item: (_severity_rank(item.severity), item.created_at or datetime.min), reverse=True)
    return items[:limit]


@router.post("/work-inbox/actions", response_model=WorkInboxActionResponse)
def work_inbox_action(
    payload: WorkInboxActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> WorkInboxActionResponse:
    job_ids: list[int] = []
    matched = 0
    updated = 0
    enqueued = 0

    if payload.action == "retry_failed_jobs":
        jobs = list(
            db.scalars(
                select(ExtractionJob)
                .where(ExtractionJob.status == "failed")
                .order_by(ExtractionJob.finished_at.desc().nullslast(), ExtractionJob.id.desc())
                .limit(payload.limit)
            ).all()
        )
        matched = len(jobs)
        for job in jobs:
            document = db.get(Document, job.document_id)
            if not document or document.deleted_at is not None:
                continue
            new_job = reprocess_document(
                db,
                document=document,
                user=user,
                job_type=job.job_type or "extract",
                enqueue=not settings.database_url.startswith("sqlite"),
            )
            job_ids.append(new_job.id)
            enqueued += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_retry_failed_jobs",
            entity_type="operations",
            details={"matched": matched, "enqueued": enqueued, "job_ids": job_ids},
        )
        db.commit()
    elif payload.action == "approve_high_confidence_ocr":
        pages = list(
            db.scalars(
                select(DocumentPage)
                .join(Document, Document.id == DocumentPage.document_id)
                .where(Document.deleted_at.is_(None))
                .where(Document.status == "processed")
                .where(DocumentPage.ocr_confidence.is_not(None))
                .where(DocumentPage.ocr_confidence >= payload.min_confidence)
                .where(DocumentPage.review_status != "approved")
                .order_by(DocumentPage.ocr_confidence.desc())
                .limit(payload.limit)
            ).all()
        )
        matched = len(pages)
        for page in pages:
            page.review_status = "approved"
            page.review_notes = "Aprobado por accion en lote."
            page.reviewed_at = datetime.utcnow()
            page.reviewed_by_id = user.id
            updated += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_approve_high_confidence_ocr",
            entity_type="document_page",
            details={"matched": matched, "updated": updated, "min_confidence": payload.min_confidence},
        )
        db.commit()
    elif payload.action == "reprocess_low_quality":
        documents = list(
            db.scalars(
                select(Document)
                .where(Document.deleted_at.is_(None))
                .where(Document.quality_status.in_(["processed_low_quality", "needs_human_review"]))
                .order_by(Document.created_at.desc())
                .limit(payload.limit)
            ).all()
        )
        matched = len(documents)
        for document in documents:
            new_job = reprocess_document(
                db,
                document=document,
                user=user,
                job_type="reprocess:ocr",
                enqueue=not settings.database_url.startswith("sqlite"),
            )
            job_ids.append(new_job.id)
            enqueued += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_reprocess_low_quality",
            entity_type="operations",
            details={"matched": matched, "enqueued": enqueued, "job_ids": job_ids},
        )
        db.commit()
    elif payload.action == "mark_duplicates_reviewed":
        documents = list(
            db.scalars(
                select(Document)
                .where(Document.deleted_at.is_(None))
                .where(Document.status == "duplicate")
                .order_by(Document.created_at.desc())
                .limit(payload.limit)
            ).all()
        )
        matched = len(documents)
        for document in documents:
            document.quality_status = "processed_ok"
            updated += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_mark_duplicates_reviewed",
            entity_type="document",
            details={"matched": matched, "updated": updated},
        )
        db.commit()

    return WorkInboxActionResponse(
        action=payload.action,
        matched=matched,
        updated=updated,
        enqueued=enqueued,
        job_ids=job_ids,
    )


@router.get("/production/checklist", response_model=ProductionChecklistResponse)
def production_checklist(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> ProductionChecklistResponse:
    health = system_health(db=db)
    queue_status = build_queue_control_status(db)
    manifest_ready = bool(settings.ai_provider and settings.ai_base_url is not None)
    items = [
        _checklist_item(
            "database",
            "Base de datos",
            health["checks"]["database"],
            "PostgreSQL responde a consultas basicas.",
            "/admin/system/health",
        ),
        _checklist_item(
            "redis",
            "Redis",
            health["checks"]["redis"],
            "Redis responde para colas, cache y notificaciones.",
            "/admin/system/health",
        ),
        _checklist_item(
            "watcher",
            "Watcher",
            health["checks"]["watcher"],
            "Vigilancia de carpetas configurada para ingesta 24h.",
            "/admin/operations/overview",
        ),
        _checklist_item(
            "disk",
            "Disco",
            health["checks"]["disk_files"],
            "Espacio disponible para originales, previews y OCR.",
            "/admin/system/health",
        ),
        ProductionChecklistItem(
            key="queues",
            title="Colas",
            status="warning" if queue_status.backpressure_active else "ok",
            description=f"Pendientes: {queue_status.pending_jobs}. Procesando: {queue_status.processing_jobs}.",
            action_url="/jobs",
        ),
        ProductionChecklistItem(
            key="backup_runbook",
            title="Backup y restore",
            status="ok" if Path("scripts/backup.ps1").exists() and Path("scripts/restore.ps1").exists() else "warning",
            description="Runbooks disponibles para PostgreSQL y /data/files.",
            action_url="/admin",
        ),
        ProductionChecklistItem(
            key="integration_manifest",
            title="Manifest IA externa",
            status="ok" if manifest_ready else "warning",
            description="Manifest y tools versionadas para que la IA externa consulte sin SQL.",
            action_url="/integrations/v1/manifest",
        ),
    ]
    return ProductionChecklistResponse(items=items)


@router.post("/rules/preview", response_model=RulePreviewResponse)
def preview_rule(
    payload: RulePreviewRequest,
    _: User = Depends(require_roles("admin", "gestor")),
) -> RulePreviewResponse:
    normalized_path = _normalize_preview_path(payload.path)
    normalized_pattern = _normalize_preview_path(payload.pattern)
    if payload.match_type == "glob":
        matches = fnmatch.fnmatch(normalized_path, normalized_pattern)
    elif payload.match_type == "regex":
        try:
            matches = re.search(normalized_pattern, normalized_path) is not None
        except re.error:
            matches = False
    else:
        matches = normalized_pattern in normalized_path
    return RulePreviewResponse(
        matches=matches,
        normalized_path=normalized_path,
        normalized_pattern=normalized_pattern,
        match_type=payload.match_type,
        specificity=len(normalized_pattern),
        tags_json=sorted({tag.strip().lower() for tag in payload.tags_json if tag.strip()}),
    )


@router.post("/integration-sandbox/execute")
def integration_sandbox_execute(
    payload: IntegrationSandboxExecuteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    client = _get_or_404(db, IntegrationClient, payload.client_id, "Integration client not found")
    if not client.is_active:
        raise HTTPException(status_code=409, detail="Integration client is inactive")
    policy = resolve_access_policy(db, payload.technician_id)
    access_scope = resolve_technician_access_scope(db, payload.technician_id)
    access_scope.allow_unassigned_documents = True
    context = IntegrationContext(
        client=client,
        technician_id=payload.technician_id,
        technician_name=payload.technician_name,
        policy=policy,
        access_scope=access_scope,
        budget_session=None,
    )
    response = execute_integration_tool(db, context=context, tool=payload.tool, arguments=payload.arguments)
    response.warnings.append("Sandbox: respuesta de prueba generada desde administracion, sin afectar produccion.")
    write_audit(
        db,
        user=user,
        action="admin_integration_sandbox_execute",
        entity_type="integration_client",
        entity_id=client.id,
        details={
            "technician_id": payload.technician_id,
            "tool": payload.tool,
            "arguments": payload.arguments,
            "request_id": response.request_id,
            "redactions": response.redactions,
        },
    )
    db.commit()
    return response


@router.post("/security/redaction-preview", response_model=RedactionPreviewResponse)
def redaction_preview(
    payload: RedactionPreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor")),
) -> RedactionPreviewResponse:
    if payload.principal_type == "user":
        principal = db.get(User, int(payload.principal_id)) if payload.principal_id.isdigit() else None
        if not principal:
            raise HTTPException(status_code=404, detail="User not found")
        scope = resolve_user_access_scope(db, principal)
        can_view_prices = scope.can_view_prices
    else:
        policy = resolve_access_policy(db, payload.principal_id)
        scope = resolve_technician_access_scope(db, payload.principal_id)
        can_view_prices = bool(policy_allows_prices(policy) or scope.can_view_prices)

    redacted_text = payload.text if can_view_prices else redact_sensitive_text(payload.text)
    redactions = [] if can_view_prices else ["ocr.money_amounts", "commercial_terms", "margins"]
    return RedactionPreviewResponse(
        principal_type=payload.principal_type,
        principal_id=payload.principal_id,
        can_view_prices=can_view_prices,
        redacted_text=redacted_text,
        redactions=redactions,
    )


@router.get("/access/effective", response_model=EffectiveAccessRead)
def effective_access(
    principal_type: str = Query(pattern="^(user|technician)$"),
    principal_id: str = Query(min_length=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    try:
        return effective_access_payload(db, principal_type=principal_type, principal_id=principal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/quality/rules", response_model=QualityRulesRead)
def quality_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return quality_rules_payload(db)


@router.get("/quality/summary", response_model=QualitySummaryRead)
def quality_summary_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return quality_summary(db)


@router.post("/quality/recalculate", response_model=QualityRecalculateResponse)
def quality_recalculate(
    payload: QualityRecalculateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> QualityRecalculateResponse:
    result = recalculate_quality(db, limit=payload.limit)
    write_audit(
        db,
        user=user,
        action="quality_recalculated",
        entity_type="document",
        details={"matched": result.matched, "updated": result.updated, "needs_review": result.needs_review},
    )
    db.commit()
    return QualityRecalculateResponse(matched=result.matched, updated=result.updated, needs_review=result.needs_review)


@router.get("/production/readiness", response_model=ProductionReadinessResponse)
def production_readiness_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return production_readiness(db)


@router.get("/storage/integrity", response_model=StorageIntegrityResponse)
def storage_integrity_endpoint(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return storage_integrity(db, limit=limit)


@router.get("/watched-files")
def watched_files(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[dict]:
    stmt = select(WatchedFile).order_by(WatchedFile.updated_at.desc())
    if status_filter:
        stmt = stmt.where(WatchedFile.status == status_filter)
    stmt = stmt.limit(limit)
    return [_watched_file_payload(row) for row in db.scalars(stmt).all()]


@router.get("/ingestion-events")
def ingestion_events(
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[dict]:
    stmt = select(IngestionEvent).order_by(IngestionEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(IngestionEvent.event_type == event_type)
    stmt = stmt.limit(limit)
    return [_ingestion_event_payload(row) for row in db.scalars(stmt).all()]


@router.get("/access-explain")
def access_explain(
    principal_type: str = Query(pattern="^(user|technician)$"),
    principal_id: str = Query(min_length=1),
    document_id: int = Query(ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    document = _get_or_404(db, Document, document_id, "Document not found")
    try:
        return explain_document_access(
            db,
            principal_type=principal_type,
            principal_id=principal_id,
            document=document,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/bulk-tags", response_model=BulkTagsResponse)
def bulk_document_tags(
    payload: BulkTagsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> BulkTagsResponse:
    add_tags = _normalized_tags(payload.add_tags)
    remove_tags = set(_normalized_tags(payload.remove_tags))
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.id.in_(payload.document_ids))
            .order_by(Document.id.asc())
        ).all()
    )
    tags_by_document: dict[str, list[str]] = {}
    for document in documents:
        metadata = ensure_document_access_metadata(db, document)
        tags = set(_normalized_tags(metadata.tags_json))
        tags.update(add_tags)
        tags.difference_update(remove_tags)
        metadata.tags_json = sorted(tags)
        tags_by_document[str(document.id)] = metadata.tags_json
    write_audit(
        db,
        user=user,
        action="document_tags_bulk_updated",
        entity_type="document",
        details={
            "document_ids": [document.id for document in documents],
            "add_tags": add_tags,
            "remove_tags": sorted(remove_tags),
        },
    )
    db.commit()
    cache_service.invalidate_search_cache()
    return BulkTagsResponse(
        matched=len(documents),
        updated=len(documents),
        document_ids=[document.id for document in documents],
        tags_by_document=tags_by_document,
    )


@router.get("/documents/{document_id}/graph")
def document_graph(
    document_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    _get_or_404(db, Document, document_id, "Document not found")
    return build_document_graph(db, document_id)


@router.get("/audit-logs", response_model=list[AuditLogRead])
def audit_logs(
    action: str | None = None,
    entity_type: str | None = None,
    user_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return list(db.scalars(stmt.offset(offset).limit(limit)).all())


@router.get("/audit-logs/export/json")
def audit_logs_export_json(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    payload = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "details_json": row.details_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return StreamingResponse(
        iter([json.dumps(payload, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=docuintel_audit_logs.json"},
    )


@router.get("/audit-logs/export/csv")
def audit_logs_export_csv(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "user_id", "action", "entity_type", "entity_id", "details_json"])
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat() if row.created_at else "",
                row.user_id or "",
                row.action,
                row.entity_type or "",
                row.entity_id or "",
                json.dumps(row.details_json or {}, ensure_ascii=False),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=docuintel_audit_logs.csv"},
    )


@router.get("/ocr-errors", response_model=list[DocumentRead])
def ocr_errors(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status.in_(["failed", "needs_review"]))
            .order_by(Document.created_at.desc())
            .limit(100)
        ).all()
    )


@router.get("/ocr-review", response_model=list[OcrReviewPageRead])
@router.get("/quality/ocr-review", response_model=list[OcrReviewPageRead])
def ocr_review(
    max_confidence: float = Query(default=0.70, ge=0, le=1),
    document_type: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[OcrReviewPageRead]:
    stmt = (
        select(DocumentPage, Document)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentPage.ocr_confidence.is_not(None))
        .where(DocumentPage.ocr_confidence < max_confidence)
        .order_by(DocumentPage.ocr_confidence.asc(), Document.created_at.desc())
    )
    if review_status:
        stmt = stmt.where(DocumentPage.review_status == review_status)
    else:
        stmt = stmt.where(DocumentPage.review_status != "approved")
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if status:
        stmt = stmt.where(Document.status == status)
    rows = db.execute(stmt.limit(limit)).all()
    return [_ocr_review_payload(page, document) for page, document in rows]


@router.patch("/ocr-review/{page_id}", response_model=OcrReviewPageRead)
@router.patch("/quality/pages/{page_id}/review", response_model=OcrReviewPageRead)
def update_ocr_review(
    page_id: int,
    payload: OcrReviewPageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> OcrReviewPageRead:
    page = db.get(DocumentPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="OCR review page not found")
    document = _get_or_404(db, Document, page.document_id, "Document not found")
    page.review_status = payload.review_status
    page.review_notes = payload.review_notes
    page.reviewed_at = datetime.utcnow()
    page.reviewed_by_id = user.id
    if payload.review_status == "rejected":
        document.status = "needs_review"
    refresh_quality_from_existing_pages(db, document)
    write_audit(
        db,
        user=user,
        action="ocr_review_page_updated",
        entity_type="document_page",
        entity_id=page.id,
        details={
            "document_id": document.id,
            "page_number": page.page_number,
            "review_status": payload.review_status,
        },
    )
    db.commit()
    db.refresh(page)
    db.refresh(document)
    return _ocr_review_payload(page, document)


@router.post("/quality/pages/{page_id}/reprocess-ocr", response_model=JobActionResponse)
def reprocess_ocr_page(
    page_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ExtractionJob:
    page = db.get(DocumentPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="OCR review page not found")
    document = _get_or_404(db, Document, page.document_id, "Document not found")
    job = reprocess_document(db, document=document, user=user, job_type="reprocess:ocr")
    write_audit(
        db,
        user=user,
        action="ocr_page_reprocess_requested",
        entity_type="document_page",
        entity_id=page.id,
        details={"document_id": document.id, "page_number": page.page_number, "job_id": job.id},
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/duplicates", response_model=list[DocumentRead])
def duplicates(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "duplicate")
            .order_by(Document.created_at.desc())
            .limit(100)
        ).all()
    )


@router.get("/hotel-chains", response_model=list[HotelChainRead])
def list_hotel_chains(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[HotelChain]:
    return list(db.scalars(select(HotelChain).order_by(HotelChain.name.asc())).all())


@router.post("/hotel-chains", response_model=HotelChainRead)
def create_hotel_chain(
    payload: HotelChainCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> HotelChain:
    chain = HotelChain(**payload.model_dump())
    db.add(chain)
    db.flush()
    write_audit(db, user=user, action="hotel_chain_created", entity_type="hotel_chain", entity_id=chain.id)
    db.commit()
    db.refresh(chain)
    return chain


@router.patch("/hotel-chains/{chain_id}", response_model=HotelChainRead)
def update_hotel_chain(
    chain_id: int,
    payload: HotelChainUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> HotelChain:
    chain = _get_or_404(db, HotelChain, chain_id, "Hotel chain not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(chain, field, value)
    write_audit(db, user=user, action="hotel_chain_updated", entity_type="hotel_chain", entity_id=chain.id)
    db.commit()
    db.refresh(chain)
    return chain


@router.get("/hotels", response_model=list[HotelRead])
def list_hotels(
    chain_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[Hotel]:
    stmt = select(Hotel).order_by(Hotel.name.asc())
    if chain_id:
        stmt = stmt.where(Hotel.chain_id == chain_id)
    return list(db.scalars(stmt).all())


@router.post("/hotels", response_model=HotelRead)
def create_hotel(payload: HotelCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> Hotel:
    _get_or_404(db, HotelChain, payload.chain_id, "Hotel chain not found")
    hotel = Hotel(**payload.model_dump())
    db.add(hotel)
    db.flush()
    write_audit(db, user=user, action="hotel_created", entity_type="hotel", entity_id=hotel.id)
    db.commit()
    db.refresh(hotel)
    return hotel


@router.patch("/hotels/{hotel_id}", response_model=HotelRead)
def update_hotel(
    hotel_id: int,
    payload: HotelUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> Hotel:
    hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
    if payload.chain_id is not None:
        _get_or_404(db, HotelChain, payload.chain_id, "Hotel chain not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(hotel, field, value)
    write_audit(db, user=user, action="hotel_updated", entity_type="hotel", entity_id=hotel.id)
    db.commit()
    db.refresh(hotel)
    return hotel


@router.get("/folder-rules", response_model=list[FolderRuleRead])
def list_folder_rules(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[FolderAssignmentRule]:
    return list(db.scalars(select(FolderAssignmentRule).order_by(FolderAssignmentRule.id.desc())).all())


@router.post("/folder-rules", response_model=FolderRuleRead)
def create_folder_rule(
    payload: FolderRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> FolderAssignmentRule:
    _validate_hotel_assignment(db, payload.chain_id, payload.hotel_id)
    rule = FolderAssignmentRule(**payload.model_dump())
    db.add(rule)
    db.flush()
    write_audit(db, user=user, action="folder_rule_created", entity_type="folder_assignment_rule", entity_id=rule.id)
    db.commit()
    cache_service.invalidate_search_cache()
    db.refresh(rule)
    return rule


@router.patch("/folder-rules/{rule_id}", response_model=FolderRuleRead)
def update_folder_rule(
    rule_id: int,
    payload: FolderRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> FolderAssignmentRule:
    rule = _get_or_404(db, FolderAssignmentRule, rule_id, "Folder rule not found")
    data = payload.model_dump(exclude_unset=True)
    _validate_hotel_assignment(db, data.get("chain_id", rule.chain_id), data.get("hotel_id", rule.hotel_id))
    for field, value in data.items():
        setattr(rule, field, value)
    write_audit(db, user=user, action="folder_rule_updated", entity_type="folder_assignment_rule", entity_id=rule.id)
    db.commit()
    cache_service.invalidate_search_cache()
    db.refresh(rule)
    return rule


@router.post("/folder-rules/apply", response_model=FolderRulesApplyResponse)
def apply_folder_rules(
    payload: FolderRulesApplyRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> dict:
    result = apply_folder_rules_to_all_documents(db, force=bool(payload.force if payload else False))
    write_audit(db, user=user, action="folder_rules_applied", entity_type="folder_assignment_rule", details=result)
    db.commit()
    cache_service.invalidate_search_cache()
    return result


@router.get("/document-access/{document_id}", response_model=DocumentAccessRead)
def get_document_access(
    document_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> DocumentAccessMetadata:
    document = _get_or_404(db, Document, document_id, "Document not found")
    return ensure_document_access_metadata(db, document)


@router.patch("/document-access/{document_id}", response_model=DocumentAccessRead)
def update_document_access(
    document_id: int,
    payload: DocumentAccessUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> DocumentAccessMetadata:
    document = _get_or_404(db, Document, document_id, "Document not found")
    metadata = ensure_document_access_metadata(db, document)
    data = payload.model_dump(exclude_unset=True)
    _validate_hotel_assignment(db, data.get("chain_id", metadata.chain_id), data.get("hotel_id", metadata.hotel_id))
    for field, value in data.items():
        setattr(metadata, field, value)
    if metadata.assignment_status is None:
        metadata.assignment_status = "assigned" if metadata.chain_id or metadata.hotel_id else "quarantine"
    write_audit(db, user=user, action="document_access_updated", entity_type="document", entity_id=document.id, details=data)
    db.commit()
    cache_service.invalidate_search_cache()
    db.refresh(metadata)
    return metadata


@router.get("/access-groups", response_model=list[AccessGroupRead])
def list_access_groups(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[AccessGroup]:
    return list(db.scalars(select(AccessGroup).order_by(AccessGroup.name.asc())).all())


@router.post("/access-groups", response_model=AccessGroupRead)
def create_access_group(
    payload: AccessGroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> AccessGroup:
    group = AccessGroup(**payload.model_dump())
    db.add(group)
    db.flush()
    write_audit(db, user=user, action="access_group_created", entity_type="access_group", entity_id=group.id)
    db.commit()
    cache_service.invalidate_search_cache()
    db.refresh(group)
    return group


@router.patch("/access-groups/{group_id}", response_model=AccessGroupRead)
def update_access_group(
    group_id: int,
    payload: AccessGroupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> AccessGroup:
    group = _get_or_404(db, AccessGroup, group_id, "Access group not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    write_audit(db, user=user, action="access_group_updated", entity_type="access_group", entity_id=group.id)
    db.commit()
    cache_service.invalidate_search_cache()
    db.refresh(group)
    return group


@router.post("/access-groups/{group_id}/members", response_model=AccessGroupMemberRead)
@router.patch("/access-groups/{group_id}/members", response_model=AccessGroupMemberRead)
def upsert_access_group_member(
    group_id: int,
    payload: AccessGroupMemberUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> AccessGroupMember:
    _get_or_404(db, AccessGroup, group_id, "Access group not found")
    member = db.scalar(
        select(AccessGroupMember)
        .where(AccessGroupMember.group_id == group_id)
        .where(AccessGroupMember.principal_type == payload.principal_type)
        .where(AccessGroupMember.principal_id == payload.principal_id)
    )
    if not member:
        member = AccessGroupMember(group_id=group_id, **payload.model_dump())
        db.add(member)
        db.flush()
    write_audit(db, user=user, action="access_group_member_upserted", entity_type="access_group", entity_id=group_id)
    db.commit()
    cache_service.invalidate_search_cache()
    db.refresh(member)
    return member


@router.get("/quarantine-documents", response_model=list[DocumentRead])
def quarantine_documents(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .outerjoin(DocumentAccessMetadata, DocumentAccessMetadata.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where((DocumentAccessMetadata.id.is_(None)) | (DocumentAccessMetadata.assignment_status != "assigned"))
            .order_by(Document.created_at.desc())
            .limit(limit)
        ).all()
    )


@router.get("/sensitive-tags", response_model=list[SensitiveTagRead])
@router.get("/security/tags", response_model=list[SensitiveTagRead])
def list_sensitive_tags(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[SensitiveTag]:
    return list(db.scalars(select(SensitiveTag).order_by(SensitiveTag.name.asc())).all())


@router.post("/sensitive-tags", response_model=SensitiveTagRead)
@router.post("/security/tags", response_model=SensitiveTagRead)
def create_sensitive_tag(
    payload: SensitiveTagCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> SensitiveTag:
    tag = SensitiveTag(**payload.model_dump())
    db.add(tag)
    db.flush()
    write_audit(db, user=user, action="sensitive_tag_created", entity_type="sensitive_tag", entity_id=tag.id)
    db.commit()
    db.refresh(tag)
    return tag


@router.patch("/sensitive-tags/{tag_id}", response_model=SensitiveTagRead)
def update_sensitive_tag(
    tag_id: int,
    payload: SensitiveTagUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> SensitiveTag:
    tag = _get_or_404(db, SensitiveTag, tag_id, "Sensitive tag not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tag, field, value)
    write_audit(db, user=user, action="sensitive_tag_updated", entity_type="sensitive_tag", entity_id=tag.id)
    db.commit()
    db.refresh(tag)
    return tag


def _watched_file_payload(row: WatchedFile) -> dict:
    return {
        "id": row.id,
        "path": row.path,
        "status": row.status,
        "size_bytes": row.size_bytes,
        "mtime_epoch": row.mtime_epoch,
        "document_id": row.document_id,
        "job_id": row.job_id,
        "error_message": row.error_message,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "updated_at": row.updated_at,
    }


def _document_operation_payload(document: Document) -> dict:
    return {
        "id": document.id,
        "original_filename": document.original_filename,
        "source_path": document.source_path,
        "file_size": document.file_size,
        "document_type": document.document_type,
        "status": document.status,
        "quality_status": document.quality_status,
        "quality_score": document.quality_score,
        "confidence": document.confidence,
        "page_count": document.page_count,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "processed_at": document.processed_at.isoformat() if document.processed_at else None,
    }


def _normalized_tags(values) -> list[str]:
    if not values:
        return []
    return sorted({str(value).strip().lower() for value in values if str(value).strip()})


def _severity_rank(severity: str) -> int:
    return {"info": 1, "warning": 2, "error": 3}.get(severity, 0)


def _checklist_item(key: str, title: str, check: dict, ok_description: str, action_url: str) -> ProductionChecklistItem:
    status = str(check.get("status", "warning"))
    normalized_status = status if status in {"ok", "warning", "error"} else "warning"
    detail = check.get("detail")
    description = ok_description if normalized_status == "ok" and not detail else str(detail or ok_description)
    return ProductionChecklistItem(
        key=key,
        title=title,
        status=normalized_status,
        description=description,
        action_url=action_url,
    )


def _normalize_preview_path(value: str) -> str:
    clean = value.replace("\\", "/").strip().lower()
    clean = re.sub(r"/+", "/", clean)
    return clean


def _ingestion_event_payload(row: IngestionEvent) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "source_path": row.source_path,
        "document_id": row.document_id,
        "job_id": row.job_id,
        "watched_file_id": row.watched_file_id,
        "details_json": row.details_json,
        "error_message": row.error_message,
        "created_at": row.created_at,
    }


def _ocr_review_payload(page: DocumentPage, document: Document) -> OcrReviewPageRead:
    text = page.text or ""
    blocks = list(
        db_blocks
        for db_blocks in page.blocks
    )
    return OcrReviewPageRead(
        document_id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        status=document.status,
        confidence=document.confidence,
        page_id=page.id,
        page_number=page.page_number,
        ocr_confidence=page.ocr_confidence,
        review_status=page.review_status,
        review_notes=page.review_notes,
        reviewed_at=page.reviewed_at,
        reviewed_by_id=page.reviewed_by_id,
        quality_status=document.quality_status,
        quality_score=document.quality_score,
        quality_flags_json=document.quality_flags_json or [],
        text=text,
        text_excerpt=text[:800],
        blocks=[
            {
                "id": block.id,
                "block_type": block.block_type,
                "text": block.text,
                "bbox_x1": block.bbox_x1,
                "bbox_y1": block.bbox_y1,
                "bbox_x2": block.bbox_x2,
                "bbox_y2": block.bbox_y2,
                "confidence": block.confidence,
                "source_engine": block.source_engine,
            }
            for block in sorted(blocks, key=lambda item: item.id)
        ],
        preview_url=f"/documents/{document.id}/pages/{page.page_number}/image" if page.image_path else None,
        created_at=page.created_at,
    )


def _get_or_404(db: Session, model, item_id: int, message: str):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(status_code=404, detail=message)
    return item


def _validate_hotel_assignment(db: Session, chain_id: int | None, hotel_id: int | None) -> None:
    if chain_id:
        _get_or_404(db, HotelChain, chain_id, "Hotel chain not found")
    if hotel_id:
        hotel = _get_or_404(db, Hotel, hotel_id, "Hotel not found")
        if chain_id and hotel.chain_id != chain_id:
            raise HTTPException(status_code=400, detail="Hotel does not belong to selected chain")


def _new_api_key() -> str:
    return f"di_{secrets.token_urlsafe(32)}"


def _normalize_scopes(scopes: list[str]) -> list[str]:
    allowed = {"read", "upload", "admin"}
    normalized = sorted({scope.strip().lower() for scope in scopes if scope and scope.strip()})
    invalid = [scope for scope in normalized if scope not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid scopes: {', '.join(invalid)}")
    return normalized or ["read"]


def _database_health(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _redis_health() -> dict:
    try:
        cache_service.client.ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _disk_health(path: Path) -> dict:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
        free_ratio = usage.free / usage.total if usage.total else 0
        status = "ok" if free_ratio >= 0.10 else "warning"
        return {
            "status": status,
            "path": str(path),
            "total": usage.total,
            "free": usage.free,
            "free_ratio": round(free_ratio, 4),
        }
    except Exception as exc:
        return {"status": "error", "path": str(path), "detail": str(exc)}


def _watcher_health(db: Session) -> dict:
    if not settings.watcher_enabled:
        return {"status": "ok", "enabled": False}
    latest = db.scalar(select(func.max(WatchedFile.updated_at)))
    if not latest:
        return {"status": "ok", "enabled": True, "detail": "No watched files recorded yet"}
    return {"status": "ok", "enabled": True, "last_seen_at": latest.isoformat()}


def _queue_health(db: Session) -> dict:
    status = build_queue_control_status(db)
    if status.backpressure_active:
        return {"status": "warning", "detail": "Backpressure active", "pending_jobs": status.pending_jobs}
    return {
        "status": "ok",
        "ingestion_paused": status.ingestion_paused,
        "pending_jobs": status.pending_jobs,
        "processing_jobs": status.processing_jobs,
    }
