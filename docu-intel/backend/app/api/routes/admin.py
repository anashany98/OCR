from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
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
    OcrReviewPageRead,
    OcrReviewPageUpdate,
    ProcessingMetricsRead,
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
from app.services.budget_scope import ensure_budget_scope
from app.services.cache import cache_service
from app.services.document_graph import build_document_graph
from app.services.maintenance import build_maintenance_report, build_operations_status
from app.services.operations import build_admin_alerts, build_processing_metrics
from app.services.tenant_access import apply_folder_rules_to_all_documents, ensure_document_access_metadata

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


@router.get("/operations-status")
def operations_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_operations_status(db)


@router.get("/maintenance-report")
def maintenance_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_maintenance_report(db)


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
def ocr_review(
    max_confidence: float = Query(default=0.70, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[OcrReviewPageRead]:
    rows = db.execute(
        select(DocumentPage, Document)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentPage.ocr_confidence.is_not(None))
        .where(DocumentPage.ocr_confidence < max_confidence)
        .where(DocumentPage.review_status != "approved")
        .order_by(DocumentPage.ocr_confidence.asc(), Document.created_at.desc())
        .limit(limit)
    ).all()
    return [_ocr_review_payload(page, document) for page, document in rows]


@router.patch("/ocr-review/{page_id}", response_model=OcrReviewPageRead)
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
def list_sensitive_tags(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[SensitiveTag]:
    return list(db.scalars(select(SensitiveTag).order_by(SensitiveTag.name.asc())).all())


@router.post("/sensitive-tags", response_model=SensitiveTagRead)
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
        text=text,
        text_excerpt=text[:800],
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
