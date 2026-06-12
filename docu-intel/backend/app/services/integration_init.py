from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import IntegrationClient, SensitiveTag
from app.services.access_policy import ensure_default_access_policies
from app.services.integration_security import hash_integration_api_key


def create_initial_integration_data(db: Session) -> None:
    ensure_default_access_policies(db)
    _ensure_default_sensitive_tags(db)
    for definition in _parse_integration_clients(settings.integration_clients):
        existing = db.scalar(
            select(IntegrationClient).where(IntegrationClient.name == definition["name"])
        )
        if existing:
            existing.scopes_json = definition["scopes"]
            existing.is_active = True
            if definition["api_key"]:
                existing.api_key_hash = hash_integration_api_key(definition["api_key"])
            continue
        db.add(
            IntegrationClient(
                name=definition["name"],
                api_key_hash=hash_integration_api_key(definition["api_key"]),
                scopes_json=definition["scopes"],
                is_active=True,
            )
        )
    db.commit()


def _parse_integration_clients(raw_value: str) -> list[dict]:
    definitions: list[dict] = []
    for raw_item in (raw_value or "").split(";"):
        item = raw_item.strip()
        if not item:
            continue
        parts = item.split(":", 2)
        if len(parts) != 3:
            continue
        name, api_key, scopes_raw = parts
        scopes = [scope.strip() for scope in scopes_raw.split(",") if scope.strip()]
        if name.strip() and api_key:
            definitions.append(
                {"name": name.strip(), "api_key": api_key, "scopes": scopes or ["read"]}
            )
    return definitions


def _ensure_default_sensitive_tags(db: Session) -> None:
    defaults = {
        "contabilidad": "Documentos contables o de facturacion sensible.",
        "administracion": "Documentos administrativos no operativos.",
        "rrhh": "Recursos humanos y datos laborales.",
        "direccion": "Documentos reservados a direccion.",
        "legal": "Contratos o documentacion legal sensible.",
        "precios": "Precios e importes comerciales.",
        "margenes": "Margenes o condiciones comerciales internas.",
        "proveedores": "Informacion sensible de proveedores.",
        "clientes": "Informacion sensible de clientes.",
    }
    existing = {name for name in db.scalars(select(SensitiveTag.name)).all()}
    for name, description in defaults.items():
        if name not in existing:
            db.add(SensitiveTag(name=name, description=description, is_active=True))
