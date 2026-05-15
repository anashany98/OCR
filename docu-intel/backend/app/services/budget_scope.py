from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import _encode_jwt, decode_access_token
from app.models import ApiClientBudgetScope, BudgetScope, Document


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
    marker_candidates = ("inbox", "processing", "presupuestos")
    for marker in marker_candidates:
        lowered = [part.lower() for part in parts]
        if marker not in lowered:
            continue
        index = lowered.index(marker)
        if index + 1 >= len(parts):
            continue
        candidate = _clean_budget_code(parts[index + 1])
        if candidate:
            return candidate
    if len(parts) >= 2:
        candidate = _clean_budget_code(parts[-2])
        if candidate:
            return candidate
    return None


def ensure_budget_scope(db: Session, budget_code: str, *, source_path: str | None = None) -> BudgetScope:
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


def assign_document_budget_scope(db: Session, document: Document, *, budget_code: str | None = None) -> BudgetScope | None:
    resolved_code = budget_code or extract_budget_code_from_path(document.source_path)
    if not resolved_code:
        return None
    scope = ensure_budget_scope(db, resolved_code, source_path=document.source_path)
    document.budget_scope_id = scope.id
    db.flush()
    return scope


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
    return _encode_jwt(
        {
            "sub": "integration_budget_session",
            "typ": "budget_session",
            "jti": str(uuid4()),
            "client_id": client_id,
            "technician_id": technician_id,
            "budget_scope_id": budget_scope_id,
            "budget_code": budget_code,
            "can_see_amounts": bool(can_see_amounts),
            "iat": now,
            "exp": expires_at,
        }
    )


def decode_budget_session_token(token: str) -> BudgetSessionClaims:
    payload = decode_access_token(token)
    if payload.get("typ") != "budget_session" or payload.get("sub") != "integration_budget_session":
        raise ValueError("Invalid budget session token")
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
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,119}", candidate):
        return None
    return candidate
