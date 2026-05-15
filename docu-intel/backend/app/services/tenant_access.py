from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccessGroup,
    AccessGroupMember,
    Budget,
    Document,
    DocumentAccessMetadata,
    FolderAssignmentRule,
    Hotel,
    Order,
    Plan,
    User,
)


class HasDocumentId(Protocol):
    document_id: int


T = TypeVar("T", bound=HasDocumentId)


@dataclass
class AccessScope:
    principal_type: str
    principal_id: str
    allow_all_hotels: bool = False
    chain_ids: set[int] = field(default_factory=set)
    hotel_ids: set[int] = field(default_factory=set)
    denied_tags: set[str] = field(default_factory=set)
    can_view_prices: bool = False
    can_search_budgets: bool = False
    is_admin: bool = False

    @property
    def has_location_scope(self) -> bool:
        return self.allow_all_hotels or bool(self.chain_ids or self.hotel_ids)


def resolve_user_access_scope(db: Session, user: User) -> AccessScope:
    if user.role == "admin":
        return AccessScope(
            principal_type="user",
            principal_id=str(user.id),
            allow_all_hotels=True,
            can_view_prices=True,
            can_search_budgets=True,
            is_admin=True,
        )
    return _resolve_group_scope(db, principal_type="user", principal_id=str(user.id))


def resolve_technician_access_scope(db: Session, technician_id: str) -> AccessScope:
    return _resolve_group_scope(db, principal_type="technician", principal_id=technician_id)


def _resolve_group_scope(db: Session, *, principal_type: str, principal_id: str) -> AccessScope:
    scope = AccessScope(principal_type=principal_type, principal_id=principal_id)
    groups = list(
        db.scalars(
            select(AccessGroup)
            .join(AccessGroupMember, AccessGroupMember.group_id == AccessGroup.id)
            .where(AccessGroup.is_active.is_(True))
            .where(AccessGroupMember.principal_type == principal_type)
            .where(AccessGroupMember.principal_id == principal_id)
        ).all()
    )
    for group in groups:
        permissions = group.permissions_json or {}
        scope.allow_all_hotels = scope.allow_all_hotels or bool(permissions.get("allow_all_hotels"))
        scope.chain_ids.update(_int_set(permissions.get("chain_ids")))
        scope.hotel_ids.update(_int_set(permissions.get("hotel_ids")))
        scope.denied_tags.update(_tag_set(permissions.get("denied_tags")))
        scope.can_view_prices = scope.can_view_prices or bool(permissions.get("can_view_prices"))
        scope.can_search_budgets = scope.can_search_budgets or bool(permissions.get("can_search_budgets"))
    return scope


def can_access_document(db: Session, document: Document | None, scope: AccessScope) -> bool:
    if not document or document.deleted_at is not None:
        return False
    if scope.is_admin:
        return True
    metadata = get_document_access_metadata(db, document.id)
    return metadata_allows_scope(metadata, scope)


def metadata_allows_scope(metadata: DocumentAccessMetadata | None, scope: AccessScope) -> bool:
    if scope.is_admin:
        return True
    if not metadata or metadata.assignment_status != "assigned":
        return False
    tags = _tag_set(metadata.tags_json)
    if scope.denied_tags & tags:
        return False
    if scope.allow_all_hotels:
        return True
    if metadata.hotel_id is not None and metadata.hotel_id in scope.hotel_ids:
        return True
    if metadata.chain_id is not None and metadata.chain_id in scope.chain_ids:
        return True
    return False


def filter_documents_for_scope(db: Session, documents: Iterable[Document], scope: AccessScope) -> list[Document]:
    if scope.is_admin:
        return [document for document in documents if document.deleted_at is None]
    metadata_by_document = _metadata_by_document(db, [document.id for document in documents])
    return [
        document
        for document in documents
        if document.deleted_at is None and metadata_allows_scope(metadata_by_document.get(document.id), scope)
    ]


def filter_document_ids_for_scope(db: Session, document_ids: Iterable[int], scope: AccessScope) -> set[int]:
    ids = {int(document_id) for document_id in document_ids if document_id is not None}
    if scope.is_admin:
        return ids
    metadata_by_document = _metadata_by_document(db, ids)
    return {
        document_id
        for document_id in ids
        if metadata_allows_scope(metadata_by_document.get(document_id), scope)
    }


def filter_records_by_document_scope(db: Session, records: Iterable[T], scope: AccessScope) -> list[T]:
    records_list = list(records)
    allowed_document_ids = filter_document_ids_for_scope(db, [record.document_id for record in records_list], scope)
    return [record for record in records_list if record.document_id in allowed_document_ids]


def filter_search_results_for_scope(db: Session, results: Iterable, scope: AccessScope) -> list:
    results_list = list(results)
    allowed_document_ids = filter_document_ids_for_scope(db, [result.document_id for result in results_list], scope)
    return [result for result in results_list if result.document_id in allowed_document_ids]


def get_document_access_metadata(db: Session, document_id: int) -> DocumentAccessMetadata | None:
    return db.scalar(select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id == document_id))


def ensure_document_access_metadata(db: Session, document: Document) -> DocumentAccessMetadata:
    metadata = get_document_access_metadata(db, document.id)
    if metadata:
        return metadata
    metadata = DocumentAccessMetadata(
        document_id=document.id,
        assignment_status="quarantine",
        assignment_source="none",
        tags_json=[],
    )
    db.add(metadata)
    db.flush()
    return metadata


def apply_folder_rules_to_document(db: Session, document: Document, *, force: bool = False) -> DocumentAccessMetadata:
    metadata = ensure_document_access_metadata(db, document)
    if metadata.locked_manual and not force:
        return metadata

    source = _normalize_path(document.source_path or document.original_filename or "")
    rules = list(db.scalars(select(FolderAssignmentRule).where(FolderAssignmentRule.is_active.is_(True))).all())
    matches = [rule for rule in rules if _rule_matches(rule, source)]
    if not matches:
        _set_quarantine(metadata, source="none")
        db.flush()
        return metadata

    max_specificity = max(_specificity(rule) for rule in matches)
    top_matches = [rule for rule in matches if _specificity(rule) == max_specificity]
    first = top_matches[0]
    if any(_rule_assignment_signature(rule, db) != _rule_assignment_signature(first, db) for rule in top_matches[1:]):
        _set_quarantine(metadata, source="conflict")
        db.flush()
        return metadata

    chain_id, hotel_id = _chain_hotel_from_rule(first, db)
    metadata.chain_id = chain_id
    metadata.hotel_id = hotel_id
    metadata.assignment_status = "assigned" if chain_id or hotel_id else "quarantine"
    metadata.assignment_source = "folder_rule" if metadata.assignment_status == "assigned" else "none"
    metadata.tags_json = _tags(first.tags_json)
    metadata.locked_manual = False
    db.flush()
    return metadata


def apply_folder_rules_to_all_documents(db: Session, *, force: bool = False) -> dict[str, int]:
    documents = list(db.scalars(select(Document).where(Document.deleted_at.is_(None))).all())
    assigned = 0
    quarantined = 0
    skipped = 0
    for document in documents:
        metadata = get_document_access_metadata(db, document.id)
        if metadata and metadata.locked_manual and not force:
            skipped += 1
            continue
        metadata = apply_folder_rules_to_document(db, document, force=force)
        if metadata.assignment_status == "assigned":
            assigned += 1
        else:
            quarantined += 1
    db.flush()
    return {"matched": len(documents), "assigned": assigned, "quarantined": quarantined, "skipped": skipped}


def scope_payload(scope: AccessScope) -> dict:
    return {
        "principal_type": scope.principal_type,
        "principal_id": scope.principal_id,
        "allow_all_hotels": scope.allow_all_hotels,
        "chain_ids": sorted(scope.chain_ids),
        "hotel_ids": sorted(scope.hotel_ids),
        "denied_tags": sorted(scope.denied_tags),
    }


def _metadata_by_document(db: Session, document_ids: Iterable[int]) -> dict[int, DocumentAccessMetadata]:
    ids = list({int(document_id) for document_id in document_ids if document_id is not None})
    if not ids:
        return {}
    rows = db.scalars(select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id.in_(ids))).all()
    return {row.document_id: row for row in rows}


def _rule_matches(rule: FolderAssignmentRule, source: str) -> bool:
    pattern = _normalize_path(rule.pattern)
    if not pattern:
        return False
    if rule.match_type == "glob":
        return fnmatch.fnmatch(source, pattern)
    if rule.match_type == "regex":
        try:
            return re.search(pattern, source) is not None
        except re.error:
            return False
    return pattern in source


def _specificity(rule: FolderAssignmentRule) -> int:
    return len(_normalize_path(rule.pattern))


def _rule_assignment_signature(rule: FolderAssignmentRule, db: Session) -> tuple[int | None, int | None, tuple[str, ...]]:
    chain_id, hotel_id = _chain_hotel_from_rule(rule, db)
    return chain_id, hotel_id, tuple(_tags(rule.tags_json))


def _chain_hotel_from_rule(rule: FolderAssignmentRule, db: Session) -> tuple[int | None, int | None]:
    chain_id = rule.chain_id
    hotel_id = rule.hotel_id
    if hotel_id and not chain_id:
        hotel = db.get(Hotel, hotel_id)
        chain_id = hotel.chain_id if hotel else None
    return chain_id, hotel_id


def _set_quarantine(metadata: DocumentAccessMetadata, *, source: str) -> None:
    metadata.chain_id = None
    metadata.hotel_id = None
    metadata.assignment_status = "quarantine"
    metadata.assignment_source = source
    metadata.tags_json = _tags(metadata.tags_json)


def _normalize_path(value: str) -> str:
    clean = value.replace("\\", "/").strip().lower()
    clean = re.sub(r"/+", "/", clean)
    return clean


def _int_set(value) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for item in value:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _tag_set(value) -> set[str]:
    return set(_tags(value))


def _tags(value) -> list[str]:
    if not value:
        return []
    return sorted({str(item).strip().lower() for item in value if str(item).strip()})
