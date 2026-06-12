from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessGroup, AccessGroupMember, User
from app.services.access_policy import (
    policy_allows_prices,
    policy_allows_budget_search,
    resolve_access_policy,
)
from app.services.integration_tools import REDACTED_BUDGET_FIELDS
from app.services.tenant_access import (
    AccessScope,
    resolve_technician_access_scope,
    resolve_user_access_scope,
    scope_payload,
)


def effective_access_payload(db: Session, *, principal_type: str, principal_id: str) -> dict:
    if principal_type == "user":
        user = db.get(User, int(principal_id)) if principal_id.isdigit() else None
        if not user:
            raise ValueError("User not found")
        scope = resolve_user_access_scope(db, user)
        role = user.role
        can_view_prices = scope.can_view_prices
        can_search_budgets = scope.can_search_budgets
    elif principal_type == "technician":
        scope = resolve_technician_access_scope(db, principal_id)
        policy = resolve_access_policy(db, principal_id)
        role = "technician"
        can_view_prices = bool(scope.can_view_prices or policy_allows_prices(policy))
        can_search_budgets = bool(scope.can_search_budgets or policy_allows_budget_search(policy))
    else:
        raise ValueError("Invalid principal_type")

    allowed_document_types = _allowed_document_types(
        db, principal_type=principal_type, principal_id=principal_id, scope=scope
    )
    payload = scope_payload(scope)
    payload.update(
        {
            "role": role,
            "principal_type": principal_type,
            "principal_id": principal_id,
            "can_view_prices": can_view_prices,
            "can_search_budgets": can_search_budgets,
            "allowed_document_types": allowed_document_types,
            "redacted_fields": [] if can_view_prices else list(REDACTED_BUDGET_FIELDS),
            "group_count": scope.group_count,
        }
    )
    return payload


def _allowed_document_types(
    db: Session, *, principal_type: str, principal_id: str, scope: AccessScope
) -> list[str]:
    if scope.allowed_document_types:
        return sorted(scope.allowed_document_types)
    groups = db.scalars(
        select(AccessGroup)
        .join(AccessGroupMember, AccessGroupMember.group_id == AccessGroup.id)
        .where(AccessGroup.is_active.is_(True))
        .where(AccessGroupMember.principal_type == principal_type)
        .where(AccessGroupMember.principal_id == principal_id)
    ).all()
    values: set[str] = set()
    for group in groups:
        for item in (group.permissions_json or {}).get("allowed_document_types") or []:
            clean = str(item).strip().lower()
            if clean:
                values.add(clean)
    return sorted(values)
