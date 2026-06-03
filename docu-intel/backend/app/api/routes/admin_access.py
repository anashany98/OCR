import fnmatch
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import (
    AccessGroup,
    AccessGroupMember,
    Document,
    DocumentAccessMetadata,
    FolderAssignmentRule,
    Hotel,
    HotelChain,
    SensitiveTag,
    User,
)
from app.schemas.admin import (
    BulkTagsRequest,
    BulkTagsResponse,
    EffectiveAccessRead,
    RedactionPreviewRequest,
    RedactionPreviewResponse,
    RulePreviewRequest,
    RulePreviewResponse,
)
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
from app.services.access_explain import explain_document_access
from app.services.access_policy import policy_allows_prices, resolve_access_policy
from app.services.access_review import effective_access_payload
from app.services.audit import write_audit
from app.services.cache import cache_service
from app.services.document_graph import build_document_graph
from app.services.redaction import redact_sensitive_text
from app.services.tenant_access import (
    apply_folder_rules_to_all_documents,
    ensure_document_access_metadata,
    resolve_user_access_scope,
    resolve_technician_access_scope,
)

from app.api.routes.admin_helpers import (
    _get_or_404,
    _normalize_preview_path,
    _normalized_tags,
    _validate_hotel_assignment,
)

router = APIRouter(prefix="/admin")


# ---------- access explain ----------

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


# ---------- redaction preview ----------

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


# ---------- sensitive tags ----------

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


# ---------- rules preview ----------

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


# ---------- folder rules ----------

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


# ---------- document access ----------

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


# ---------- documents bulk tags / graph ----------

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


# ---------- access groups ----------

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


# ---------- hotel chains ----------

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


# ---------- hotels ----------

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
