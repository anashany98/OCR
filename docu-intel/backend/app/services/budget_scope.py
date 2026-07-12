from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    BUDGET_SESSION_TYP,
    _encode_jwt,
    decode_integration_token,
)
from app.models import ApiClientBudgetScope, BudgetScope, Document
from app.models.project import Project


@dataclass(frozen=True)
class BudgetSessionClaims:
    client_id: int
    technician_id: str
    budget_scope_id: int
    budget_code: str
    can_see_amounts: bool
    expires_at: int
    token_id: str


def extract_budget_code_from_path(path: str | None) -> str | None:
    if not path:
        return None
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        return None
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"/", ""}]

    # Pattern 1: "Presupuesto XXXXXX" as a folder name (e.g. "Presupuesto 251234")
    # This is the dominant convention in the TEST2025 dataset.
    for part in reversed(parts):
        m = re.match(r"(?i)^presupuesto\s+(\S+)", part)
        if m:
            candidate = _clean_budget_code(m.group(1))
            if candidate:
                return candidate

    # Pattern 2: marker-based (inbox/processing/presupuestos → next folder)
    marker_candidates = ("inbox", "processing", "presupuestos")
    lowered = [part.lower() for part in parts]
    for marker in marker_candidates:
        if marker not in lowered:
            continue
        index = lowered.index(marker)
        if index + 1 >= len(parts):
            continue
        candidate = _clean_budget_code(parts[index + 1])
        if candidate:
            return candidate

    # Pattern 3: second-to-last folder (fallback)
    if len(parts) >= 2:
        candidate = _clean_budget_code(parts[-2])
        if candidate:
            return candidate
    return None


def ensure_budget_scope(
    db: Session, budget_code: str, *, source_path: str | None = None
) -> BudgetScope:
    clean = _clean_budget_code(budget_code)
    if not clean:
        raise ValueError("Invalid budget code")
    scope = db.scalar(select(BudgetScope).where(BudgetScope.budget_code == clean))
    if scope:
        if source_path and not scope.source_path:
            scope.source_path = source_path
        return scope
    scope = BudgetScope(
        budget_code=clean,
        source_path=source_path,
        display_name=f"Presupuesto {clean}",
        status="pending",
    )
    db.add(scope)
    db.flush()
    return scope


def get_or_create_budget_scope(
    db: Session,
    year: int,
    brand_id: int,
    hotel_id: int | None,
    budget_code: str,
) -> BudgetScope:
    """Return the deterministic budget identity for one physical context."""
    clean = _clean_budget_code(budget_code)
    if not clean:
        raise ValueError("Invalid budget code")
    stmt = select(BudgetScope).where(
        BudgetScope.year == year,
        BudgetScope.brand_id == brand_id,
        BudgetScope.hotel_id.is_(None) if hotel_id is None else BudgetScope.hotel_id == hotel_id,
        BudgetScope.budget_code == clean,
    )
    scope = db.scalar(stmt)
    if scope:
        return scope
    context_key = f"{year}:{brand_id}:{hotel_id if hotel_id is not None else '-'}:{clean}"
    scope = BudgetScope(
        year=year,
        brand_id=brand_id,
        hotel_id=hotel_id,
        budget_code=clean,
        context_key=context_key,
        display_name=f"Presupuesto {clean}",
        status="pending",
        legacy_unscoped=False,
    )
    db.add(scope)
    db.flush()
    return scope


def get_or_create_project_for_budget(
    db: Session,
    year: int,
    brand_id: int,
    hotel_id: int | None,
    budget_scope_id: int,
) -> Project:
    """Create exactly one project for an explicitly contextual budget."""
    stmt = select(Project).where(
        Project.year == year,
        Project.brand_id == brand_id,
        Project.primary_budget_scope_id == budget_scope_id,
        Project.hotel_id.is_(None) if hotel_id is None else Project.hotel_id == hotel_id,
    )
    project = db.scalar(stmt)
    if project:
        return project
    project = Project(
        year=year,
        brand_id=brand_id,
        hotel_id=hotel_id,
        primary_budget_scope_id=budget_scope_id,
        name=f"Proyecto {year}/{brand_id}/{budget_scope_id}",
    )
    db.add(project)
    db.flush()
    return project


def assign_document_budget_scope(
    db: Session, document: Document, *, budget_code: str | None = None
) -> BudgetScope | None:
    resolved_code = budget_code or extract_budget_code_from_path(document.source_path)
    if not resolved_code:
        return None
    scope = ensure_budget_scope(db, resolved_code, source_path=document.source_path)
    document.budget_scope_id = scope.id
    # Also persist the budget number as an entity so the relationship
    # graph and search can find this document by its presupuesto number.
    _upsert_budget_entity(db, document.id, resolved_code)
    db.flush()
    return scope


def _upsert_budget_entity(db, document_id: int, budget_number: str) -> None:
    """Create or update a budget_number entity for the document."""
    from app.models import DocumentEntity

    existing = db.scalar(
        select(DocumentEntity).where(
            DocumentEntity.document_id == document_id,
            DocumentEntity.entity_type == "budget_number",
        )
    )
    if existing:
        existing.entity_value = budget_number
        existing.normalized_value = budget_number.lower().strip()
    else:
        db.add(
            DocumentEntity(
                document_id=document_id,
                entity_type="budget_number",
                entity_value=budget_number,
                normalized_value=budget_number.lower().strip(),
                confidence=0.9,
            )
        )


def get_budget_scope_by_code(db: Session, budget_code: str) -> BudgetScope | None:
    clean = _clean_budget_code(budget_code)
    if not clean:
        return None
    return db.scalar(select(BudgetScope).where(BudgetScope.budget_code == clean))


def get_client_budget_permission(
    db: Session,
    *,
    client_id: int,
    budget_scope_id: int,
) -> ApiClientBudgetScope | None:
    return db.scalar(
        select(ApiClientBudgetScope)
        .where(ApiClientBudgetScope.api_client_id == client_id)
        .where(ApiClientBudgetScope.budget_scope_id == budget_scope_id)
    )


def create_budget_session_token(
    *,
    client_id: int,
    technician_id: str,
    budget_scope_id: int,
    budget_code: str,
    can_see_amounts: bool,
) -> str:
    now = int(time.time())
    expires_at = now + settings.integration_session_expire_seconds
    # AUTH-JWT-1 (Sprint 1): budget session tokens are signed with
    # the integration JWT secret, NOT the user auth secret. Even if
    # an attacker exfiltrates the user secret, they cannot forge a
    # budget session token (and vice versa).
    return _encode_jwt(
        {
            "sub": "integration_budget_session",
            "typ": BUDGET_SESSION_TYP,
            "jti": str(uuid4()),
            "client_id": client_id,
            "technician_id": technician_id,
            "budget_scope_id": budget_scope_id,
            "budget_code": budget_code,
            "can_see_amounts": bool(can_see_amounts),
            "iat": now,
            "exp": expires_at,
        },
        secret=settings.integration_jwt_secret or settings.jwt_secret,
    )


def decode_budget_session_token(token: str) -> BudgetSessionClaims:
    # AUTH-JWT-1 (Sprint 1): use the integration-side decoder so the
    # signature is verified against the integration JWT secret. A
    # user access token (signed with ``jwt_secret``) will fail
    # verification here and raise ``ValueError``.
    payload = decode_integration_token(token)
    if (
        payload.get("typ") != BUDGET_SESSION_TYP
        or payload.get("sub") != "integration_budget_session"
    ):
        raise ValueError(
            f"Invalid budget session token: typ={payload.get('typ')!r} sub={payload.get('sub')!r}"
        )
    return BudgetSessionClaims(
        client_id=int(payload["client_id"]),
        technician_id=str(payload["technician_id"]),
        budget_scope_id=int(payload["budget_scope_id"]),
        budget_code=str(payload["budget_code"]),
        can_see_amounts=bool(payload.get("can_see_amounts")),
        expires_at=int(payload["exp"]),
        token_id=str(payload["jti"]),
    )


def _clean_budget_code(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip().strip("/\\")
    if not candidate or "." in candidate:
        return None
    # Budget identifiers in the source corpus commonly use ``YYYY/NNN``.
    # This is an identifier, not a filesystem path, so accept that narrow
    # numeric form while keeping arbitrary slash-containing values rejected.
    if re.fullmatch(r"\d{4}/\d{1,115}", candidate):
        return candidate
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,119}", candidate):
        return None
    return candidate
