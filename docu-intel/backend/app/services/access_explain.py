from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Document, User
from app.services.tenant_access import (
    AccessScope,
    get_document_access_metadata,
    resolve_technician_access_scope,
    resolve_user_access_scope,
)


def resolve_scope_for_principal(db: Session, principal_type: str, principal_id: str) -> AccessScope:
    if principal_type == "user":
        user = db.get(User, int(principal_id))
        if not user:
            raise ValueError("User not found")
        return resolve_user_access_scope(db, user)
    if principal_type == "technician":
        return resolve_technician_access_scope(db, principal_id)
    raise ValueError("Unsupported principal type")


def explain_document_access(db: Session, *, principal_type: str, principal_id: str, document: Document) -> dict:
    scope = resolve_scope_for_principal(db, principal_type, principal_id)
    metadata = get_document_access_metadata(db, document.id)
    reasons: list[str] = []

    if document.deleted_at is not None:
        return {"allowed": False, "reasons": ["Documento borrado logicamente"], "scope": _scope(scope)}
    if scope.is_admin:
        return {"allowed": True, "reasons": ["Rol admin con acceso total"], "scope": _scope(scope)}
    if not metadata:
        if scope.allow_unassigned_documents:
            return {"allowed": True, "reasons": ["Perfil permite documentos sin asignacion"], "scope": _scope(scope)}
        return {"allowed": False, "reasons": ["Documento sin metadatos de acceso"], "scope": _scope(scope)}

    tags = set(metadata.tags_json or [])
    denied = scope.denied_tags & tags
    if denied:
        reasons.append(f"Documento contiene tag bloqueado: {', '.join(sorted(denied))}")
        return {"allowed": False, "reasons": reasons, "scope": _scope(scope)}

    if metadata.assignment_status != "assigned":
        if scope.allow_unassigned_documents:
            return {"allowed": True, "reasons": [f"Perfil permite documento en estado {metadata.assignment_status}"], "scope": _scope(scope)}
        return {"allowed": False, "reasons": [f"Documento en estado {metadata.assignment_status}"], "scope": _scope(scope)}

    if scope.allow_all_hotels:
        return {"allowed": True, "reasons": ["Perfil permite todos los hoteles"], "scope": _scope(scope)}
    if metadata.hotel_id and metadata.hotel_id in scope.hotel_ids:
        return {"allowed": True, "reasons": [f"Hotel autorizado: {metadata.hotel_id}"], "scope": _scope(scope)}
    if metadata.chain_id and metadata.chain_id in scope.chain_ids:
        return {"allowed": True, "reasons": [f"Cadena autorizada: {metadata.chain_id}"], "scope": _scope(scope)}
    return {"allowed": False, "reasons": ["Fuera del scope de cadena/hotel autorizado"], "scope": _scope(scope)}


def _scope(scope: AccessScope) -> dict:
    return {
        "principal_type": scope.principal_type,
        "principal_id": scope.principal_id,
        "allow_all_hotels": scope.allow_all_hotels,
        "chain_ids": sorted(scope.chain_ids),
        "hotel_ids": sorted(scope.hotel_ids),
        "denied_tags": sorted(scope.denied_tags),
        "can_view_prices": scope.can_view_prices,
        "can_search_budgets": scope.can_search_budgets,
        "is_admin": scope.is_admin,
        "allow_unassigned_documents": scope.allow_unassigned_documents,
    }
