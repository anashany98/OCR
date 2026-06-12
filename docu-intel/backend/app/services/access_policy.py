from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessPolicy, TechnicianAccessProfile

OPERARIO_MINIMO = "operario_minimo"
PRECIOS_AUTORIZADOS = "precios_autorizados"


DEFAULT_POLICIES = [
    {
        "name": OPERARIO_MINIMO,
        "description": "Acceso minimo para operarios: presupuestos exactos sin precios.",
        "is_default": True,
        "permissions_json": {
            "can_view_prices": False,
            "can_search_budgets": False,
            "can_upload_documents": True,
            "budget_lookup": "exact",
        },
    },
    {
        "name": PRECIOS_AUTORIZADOS,
        "description": "Acceso autorizado a importes estructurados y OCR.",
        "is_default": False,
        "permissions_json": {
            "can_view_prices": True,
            "can_search_budgets": True,
            "can_upload_documents": True,
            "budget_lookup": "exact",
        },
    },
]


def ensure_default_access_policies(db: Session) -> None:
    for payload in DEFAULT_POLICIES:
        existing = db.scalar(select(AccessPolicy).where(AccessPolicy.name == payload["name"]))
        if existing:
            existing.description = payload["description"]
            existing.permissions_json = payload["permissions_json"]
            existing.is_default = bool(payload["is_default"])
            continue
        db.add(AccessPolicy(**payload))
    db.flush()


def resolve_access_policy(db: Session, technician_id: str) -> AccessPolicy:
    profile = db.scalar(
        select(TechnicianAccessProfile)
        .where(TechnicianAccessProfile.technician_id == technician_id)
        .limit(1)
    )
    if profile and profile.access_policy:
        return profile.access_policy
    policy = db.scalar(select(AccessPolicy).where(AccessPolicy.is_default.is_(True)).limit(1))
    if policy:
        return policy
    ensure_default_access_policies(db)
    return db.scalar(select(AccessPolicy).where(AccessPolicy.name == OPERARIO_MINIMO).limit(1))


def policy_allows_prices(policy: AccessPolicy) -> bool:
    return bool((policy.permissions_json or {}).get("can_view_prices"))


def policy_allows_budget_search(policy: AccessPolicy) -> bool:
    return bool((policy.permissions_json or {}).get("can_search_budgets"))
