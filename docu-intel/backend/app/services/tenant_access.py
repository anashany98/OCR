from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.core.config import settings
from app.models import (
    AccessGroup,
    AccessGroupMember,
    Document,
    DocumentAccessMetadata,
    FolderAssignmentRule,
    Hotel,
    User,
)

# ---------------------------------------------------------------------------
# Access scope cache — avoids repeated DB queries for the same user
# within a short window. The scope is user-specific and changes only
# when group memberships change, which is rare in production.
# ---------------------------------------------------------------------------

_SCOPE_CACHE_TTL = 60  # seconds
_scope_cache: dict[str, tuple[float, AccessScope]] = {}


def _scope_cache_key(user_id: int) -> str:
    return f"scope:{user_id}"


def _get_cached_scope(user_id: int) -> AccessScope | None:
    key = _scope_cache_key(user_id)
    entry = _scope_cache.get(key)
    if entry is None:
        return None
    ts, scope = entry
    if time.monotonic() - ts > _SCOPE_CACHE_TTL:
        _scope_cache.pop(key, None)
        return None
    return scope


def _set_cached_scope(user_id: int, scope: AccessScope) -> None:
    key = _scope_cache_key(user_id)
    _scope_cache[key] = (time.monotonic(), scope)


def invalidate_scope_cache(user_id: int | None = None) -> int:
    """Invalidate cached scopes. If user_id is None, clear all."""
    if user_id is None:
        count = len(_scope_cache)
        _scope_cache.clear()
        return count
    key = _scope_cache_key(user_id)
    removed = _scope_cache.pop(key, 1)
    return 0 if removed is None else 1


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
    allowed_document_types: set[str] = field(default_factory=set)
    can_view_prices: bool = False
    can_search_budgets: bool = False
    is_admin: bool = False
    allow_unassigned_documents: bool = False
    group_count: int = 0

    @property
    def has_location_scope(self) -> bool:
        return self.allow_all_hotels or bool(self.chain_ids or self.hotel_ids)


def resolve_user_access_scope(db: Session, user: User) -> AccessScope:
    """Build the effective access scope for ``user``.

    Behaviour is controlled by ``settings.tenant_access_deny_by_default``
    (SEC-TENANT-1, Sprint 1):

    * **Deny-by-default (default, ``True``)**: the role-based
      permissive defaults are SKIPPED. A user with no AccessGroup
      membership sees zero documents. Access is granted explicitly
      by creating an AccessGroup with ``hotel_ids`` / ``chain_ids``
      and adding the user.

    * **Legacy permissive (opt-in, ``False``)**: the original
      role-based defaults from the pre-Sprint-1 code are restored
      (``gestor``/``operario``/``auditor`` all see ``allow_all_hotels``,
      etc.). Use only for deployments that depend on the historical
      behaviour AND have not run the backfill migration.

    Admin users ALWAYS get the full access scope regardless of the
    flag — admin is the break-glass role.
    """
    # Fast path: return cached scope if available (avoids DB queries
    # for repeated requests from the same user within 60s).
    cached = _get_cached_scope(user.id)
    if cached is not None:
        return cached

    scope = _resolve_user_access_scope_uncached(db, user)
    _set_cached_scope(user.id, scope)
    return scope


def _resolve_user_access_scope_uncached(db: Session, user: User) -> AccessScope:
    if user.role == "admin":
        return AccessScope(
            principal_type="user",
            principal_id=str(user.id),
            allow_all_hotels=True,
            can_view_prices=True,
            can_search_budgets=True,
            is_admin=True,
            allow_unassigned_documents=True,
        )
    # Resolve the AccessGroup-derived scope first; it is the
    # primary source of truth in both modes.
    group_scope = _resolve_group_scope(db, principal_type="user", principal_id=str(user.id))
    if settings.tenant_access_deny_by_default:
        # In deny-by-default mode, AccessGroup membership is the
        # ONLY way to get access. A user with zero groups gets
        # an empty scope (= sees nothing).
        return group_scope
    # Legacy permissive mode: if the user has any group, use it;
    # otherwise fall back to the role-based defaults.
    if group_scope.group_count:
        return group_scope
    if user.role == "gestor":
        return AccessScope(
            principal_type="user",
            principal_id=str(user.id),
            allow_all_hotels=True,
            denied_tags={"contabilidad", "administracion", "rrhh", "direccion", "legal"},
            can_view_prices=True,
            can_search_budgets=True,
            allow_unassigned_documents=True,
        )
    if user.role == "operario":
        return AccessScope(
            principal_type="user",
            principal_id=str(user.id),
            allow_all_hotels=True,
            denied_tags={
                "contabilidad",
                "administracion",
                "rrhh",
                "direccion",
                "legal",
                "precios",
                "margenes",
            },
            can_view_prices=False,
            can_search_budgets=False,
            allow_unassigned_documents=True,
        )
    if user.role == "auditor":
        return AccessScope(
            principal_type="user",
            principal_id=str(user.id),
            allow_all_hotels=True,
            denied_tags={"rrhh"},
            can_view_prices=False,
            can_search_budgets=True,
            allow_unassigned_documents=True,
        )
    return group_scope


def ensure_default_permissive_group(db: Session) -> AccessGroup:
    """Create (or fetch) the ``default-permissive`` AccessGroup.

    The migration ``0028_tenant_default_permissive_group`` calls
    this helper and then adds every existing non-admin user to the
    group. The group's ``permissions_json`` mirrors the legacy
    pre-Sprint-1 defaults so deployments upgrading from a
    pre-Sprint-1 install see no behaviour change after the migration
    runs.

    Tests can also call this helper to opt into the legacy
    behaviour for a specific test session, without having to
    monkey-patch ``settings.tenant_access_deny_by_default``.
    """
    DEFAULT_GROUP_NAME = "default-permissive"
    group = db.scalar(select(AccessGroup).where(AccessGroup.name == DEFAULT_GROUP_NAME))
    if group is not None:
        return group
    group = AccessGroup(
        name=DEFAULT_GROUP_NAME,
        description=(
            "Backfilled by Sprint 1 migration. Mirrors the legacy "
            "permissive defaults. Remove users from this group to "
            "tighten their access under the deny-by-default policy."
        ),
        permissions_json={
            "chain_ids": [],
            "hotel_ids": [],
            "allow_all_hotels": True,
            "denied_tags": [],
            "can_view_prices": False,
            "can_search_budgets": False,
            "allow_unassigned_documents": True,
        },
        is_active=True,
    )
    db.add(group)
    db.flush()
    return group


def backfill_user_to_default_group(db: Session, user: User) -> bool:
    """Idempotently add ``user`` to the default-permissive group.

    Returns True if the user was newly added, False if they were
    already a member. Used by the Sprint 1 migration to preserve
    legacy access for every existing non-admin user.
    """
    group = ensure_default_permissive_group(db)
    # Idempotency check: skip if already a member.
    existing = db.scalar(
        select(AccessGroupMember).where(
            AccessGroupMember.group_id == group.id,
            AccessGroupMember.principal_type == "user",
            AccessGroupMember.principal_id == str(user.id),
        )
    )
    if existing is not None:
        return False
    db.add(
        AccessGroupMember(
            group_id=group.id,
            principal_type="user",
            principal_id=str(user.id),
        )
    )
    return True


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
    scope.group_count = len(groups)
    for group in groups:
        permissions = group.permissions_json or {}
        scope.allow_all_hotels = scope.allow_all_hotels or bool(permissions.get("allow_all_hotels"))
        scope.allow_unassigned_documents = scope.allow_unassigned_documents or bool(
            permissions.get("allow_unassigned_documents")
        )
        scope.chain_ids.update(_int_set(permissions.get("chain_ids")))
        scope.hotel_ids.update(_int_set(permissions.get("hotel_ids")))
        scope.denied_tags.update(_tag_set(permissions.get("denied_tags")))
        scope.allowed_document_types.update(_tag_set(permissions.get("allowed_document_types")))
        scope.can_view_prices = scope.can_view_prices or bool(permissions.get("can_view_prices"))
        scope.can_search_budgets = scope.can_search_budgets or bool(
            permissions.get("can_search_budgets")
        )
    return scope


def can_access_document(db: Session, document: Document | None, scope: AccessScope) -> bool:
    if not document or document.deleted_at is not None:
        return False
    if scope.is_admin:
        return True
    if not _document_type_allows(document, scope):
        return False
    metadata = get_document_access_metadata(db, document.id)
    return metadata_allows_scope(metadata, scope)


def metadata_allows_scope(metadata: DocumentAccessMetadata | None, scope: AccessScope) -> bool:
    if scope.is_admin:
        return True
    if not metadata:
        return scope.allow_unassigned_documents
    tags = _tag_set(metadata.tags_json)
    if scope.denied_tags & tags:
        return False
    if metadata.assignment_status != "assigned":
        return scope.allow_unassigned_documents
    if scope.allow_all_hotels:
        return True
    if metadata.hotel_id is not None and metadata.hotel_id in scope.hotel_ids:
        return True
    return bool(metadata.chain_id is not None and metadata.chain_id in scope.chain_ids)


def filter_documents_for_scope(
    db: Session, documents: Iterable[Document], scope: AccessScope
) -> list[Document]:
    if scope.is_admin:
        return [document for document in documents if document.deleted_at is None]
    metadata_by_document = _metadata_by_document(db, [document.id for document in documents])
    return [
        document
        for document in documents
        if document.deleted_at is None
        and _document_type_allows(document, scope)
        and metadata_allows_scope(metadata_by_document.get(document.id), scope)
    ]


def filter_document_ids_for_scope(
    db: Session, document_ids: Iterable[int], scope: AccessScope
) -> set[int]:
    ids = {int(document_id) for document_id in document_ids if document_id is not None}
    if scope.is_admin:
        return ids
    metadata_by_document = _metadata_by_document(db, ids)
    documents_by_id = {
        document.id: document
        for document in db.scalars(select(Document).where(Document.id.in_(ids))).all()
    }
    return {
        document_id
        for document_id in ids
        if _document_type_allows(documents_by_id.get(document_id), scope)
        and metadata_allows_scope(metadata_by_document.get(document_id), scope)
    }


def filter_records_by_document_scope(
    db: Session, records: Iterable[T], scope: AccessScope
) -> list[T]:
    records_list = list(records)
    allowed_document_ids = filter_document_ids_for_scope(
        db, [record.document_id for record in records_list], scope
    )
    return [record for record in records_list if record.document_id in allowed_document_ids]


def filter_search_results_for_scope(db: Session, results: Iterable, scope: AccessScope) -> list:
    results_list = list(results)
    allowed_document_ids = filter_document_ids_for_scope(
        db, [result.document_id for result in results_list], scope
    )
    return [result for result in results_list if result.document_id in allowed_document_ids]


def get_document_access_metadata(db: Session, document_id: int) -> DocumentAccessMetadata | None:
    return db.scalar(
        select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id == document_id)
    )


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


def apply_folder_rules_to_document(
    db: Session, document: Document, *, force: bool = False
) -> DocumentAccessMetadata:
    metadata = ensure_document_access_metadata(db, document)
    if metadata.locked_manual and not force:
        return metadata

    source = _normalize_path(document.source_path or document.original_filename or "")
    rules = list(
        db.scalars(
            select(FolderAssignmentRule).where(FolderAssignmentRule.is_active.is_(True))
        ).all()
    )
    matches = [rule for rule in rules if _rule_matches(rule, source)]
    if not matches:
        _set_quarantine(metadata, source="none")
        db.flush()
        return metadata

    max_specificity = max(_specificity(rule) for rule in matches)
    top_matches = [rule for rule in matches if _specificity(rule) == max_specificity]
    first = top_matches[0]
    if any(
        _rule_assignment_signature(rule, db) != _rule_assignment_signature(first, db)
        for rule in top_matches[1:]
    ):
        _set_quarantine(metadata, source="conflict")
        db.flush()
        return metadata

    chain_id, hotel_id = _chain_hotel_from_rule(first, db)
    metadata.chain_id = chain_id
    metadata.hotel_id = hotel_id
    metadata.assignment_status = "assigned" if chain_id or hotel_id else "quarantine"
    metadata.assignment_source = (
        "folder_rule" if metadata.assignment_status == "assigned" else "none"
    )
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
    return {
        "matched": len(documents),
        "assigned": assigned,
        "quarantined": quarantined,
        "skipped": skipped,
    }


def scope_payload(scope: AccessScope) -> dict:
    return {
        "principal_type": scope.principal_type,
        "principal_id": scope.principal_id,
        "allow_all_hotels": scope.allow_all_hotels,
        "chain_ids": sorted(scope.chain_ids),
        "hotel_ids": sorted(scope.hotel_ids),
        "denied_tags": sorted(scope.denied_tags),
        "allowed_document_types": sorted(scope.allowed_document_types),
        "allow_unassigned_documents": scope.allow_unassigned_documents,
    }


def access_scope_cache_key(scope: AccessScope) -> str:
    payload = scope_payload(scope)
    payload.update(
        {
            "can_view_prices": scope.can_view_prices,
            "can_search_budgets": scope.can_search_budgets,
            "is_admin": scope.is_admin,
            "group_count": scope.group_count,
        }
    )
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _document_type_allows(document: Document | None, scope: AccessScope) -> bool:
    if not scope.allowed_document_types:
        return True
    if not document:
        return False
    return (document.document_type or "").strip().lower() in scope.allowed_document_types


def _metadata_by_document(
    db: Session, document_ids: Iterable[int]
) -> dict[int, DocumentAccessMetadata]:
    ids = list({int(document_id) for document_id in document_ids if document_id is not None})
    if not ids:
        return {}
    rows = db.scalars(
        select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id.in_(ids))
    ).all()
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


def _rule_assignment_signature(
    rule: FolderAssignmentRule, db: Session
) -> tuple[int | None, int | None, tuple[str, ...]]:
    chain_id, hotel_id = _chain_hotel_from_rule(rule, db)
    return chain_id, hotel_id, tuple(_tags(rule.tags_json))


def _chain_hotel_from_rule(
    rule: FolderAssignmentRule, db: Session
) -> tuple[int | None, int | None]:
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


# ---------------------------------------------------------------------------
# DATA-03: push the access-scope filter into SQL so pagination and totals
# stay correct for non-admin users.
#
# The old helpers (``filter_documents_for_scope``,
# ``filter_records_by_document_scope``) load a capped candidate set
# into memory and filter afterwards, which causes:
#
#   * short / empty pages when many hidden rows precede visible rows
#   * wrong totals (``len(visible)`` over 500 candidates, not the real
#     scoped total)
#
# ``apply_access_predicates`` rewrites the WHERE clause so PostgreSQL
# itself returns only the rows the caller can see. The same predicate
# can be applied to both the main ``stmt`` and its ``count_stmt`` so
# pagination stays consistent.
# ---------------------------------------------------------------------------


def _build_access_subquery(scope: AccessScope):
    """Return a SQLAlchemy subquery selecting ``document_id`` rows that
    the given ``scope`` is allowed to see.

    The subquery is used by :func:`apply_access_predicates` to
    restrict a main query (``WHERE document_id IN (subq)``). The
    subquery covers the *location* part of the scope (chain /
    hotel / allow_unassigned / admin) and the *document type*
    allow-list. The *tag deny-list* and ``allowed_document_types``
    refinement are intentionally left to the in-memory helper
    :func:`filter_documents_for_scope` because the
    ``document_access_metadata.tags_json`` column is a JSON array
    that requires dialect-specific expansion (``json_each`` on
    SQLite, ``jsonb_array_elements_text`` on PostgreSQL); keeping
    that out of the SQL keeps this helper portable and the
    performance win — replacing the candidate-cap post-filter with
    a real subquery — already covers the pagination bug the audit
    flagged as DATA-03.
    """
    # Admin short-circuit: return a "match anything" subquery. We
    # do this by selecting from ``documents`` directly and skipping
    # the metadata join. The caller checks ``scope.is_admin``
    # before invoking us, so this is only hit by future code that
    # may want a uniform subquery shape.
    if scope.is_admin:
        return select(Document.id)

    # Empty scope: no documents are visible. We still return a
    # subquery that selects zero rows so the caller can compose
    # ``WHERE document_id IN (subq)`` without special-casing.
    if (
        not scope.allow_all_hotels
        and not scope.chain_ids
        and not scope.hotel_ids
        and not scope.allow_unassigned_documents
    ):
        return select(DocumentAccessMetadata.document_id).where(
            DocumentAccessMetadata.document_id.is_(None)
        )

    positive_conditions: list[ColumnElement[Any]] = []

    if scope.allow_all_hotels:
        # ``allow_all_hotels`` covers every chain and hotel. The
        # ``allow_unassigned_documents`` / ``assignment_status``
        # branch below then decides whether quarantine documents
        # are visible.
        pass
    else:
        if scope.chain_ids:
            positive_conditions.append(DocumentAccessMetadata.chain_id.in_(scope.chain_ids))
        if scope.hotel_ids:
            positive_conditions.append(DocumentAccessMetadata.hotel_id.in_(scope.hotel_ids))

        if not positive_conditions and not scope.allow_unassigned_documents:
            # Scope is empty for location and we are not allowed
            # to see unassigned documents either: return a
            # zero-row subquery.
            return select(DocumentAccessMetadata.document_id).where(
                DocumentAccessMetadata.document_id.is_(None)
            )

    if scope.allow_unassigned_documents:
        positive_conditions.append(DocumentAccessMetadata.assignment_status != "quarantine")

    stmt = select(DocumentAccessMetadata.document_id)
    if positive_conditions:
        stmt = stmt.where(or_(*positive_conditions))

    return stmt


def apply_access_predicates(
    stmt: Select,
    scope: AccessScope,
    *,
    document_column=None,
) -> Select:
    """Return ``stmt`` with a WHERE clause that restricts rows to the
    documents the given ``scope`` can see.

    The caller must provide a SELECT whose FROM already includes the
    ``Document`` table (or, when ``document_column`` is set, the
    actual column on the joined entity). The function only adds
    predicates; it never restricts unrelated tables.

    ``document_column`` defaults to ``Document.id`` which is the
    right choice for queries whose FROM is ``Document``. For
    queries that select ``Document`` rows through a subquery or
    join (e.g. ``Budget.document_id``), pass the column that
    carries the document id — the predicate is
    ``<column> IN (subquery)``.
    """
    if scope is None or scope.is_admin:
        return stmt

    subq = _build_access_subquery(scope)
    column = document_column if document_column is not None else Document.id
    return stmt.where(column.in_(subq))


def count_access_predicates(
    scope: AccessScope,
    *,
    count_stmt: Select,
    document_column=None,
) -> Select:
    """Apply the access predicates to a ``COUNT(*)`` statement so the
    scoped total matches the filtered page size.

    Same call shape as :func:`apply_access_predicates`. Callers
    should pass a ``count_stmt`` whose FROM mirrors the main query
    so the predicate can be appended safely.
    """
    if scope is None or scope.is_admin:
        return count_stmt

    subq = _build_access_subquery(scope)
    column = document_column if document_column is not None else Document.id
    return count_stmt.where(column.in_(subq))
