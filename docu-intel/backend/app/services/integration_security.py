from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models import AccessPolicy, IntegrationClient
from app.services.access_policy import resolve_access_policy
from app.services.budget_scope import BudgetSessionClaims, decode_budget_session_token
from app.services.integration_rate_limit import enforce_integration_rate_limit
from app.services.tenant_access import AccessScope, resolve_technician_access_scope


@dataclass
class IntegrationContext:
    client: IntegrationClient
    technician_id: str
    technician_name: str | None
    policy: AccessPolicy
    access_scope: AccessScope
    budget_session: BudgetSessionClaims | None = None


def hash_integration_api_key(api_key: str) -> str:
    digest = hmac.new(settings.jwt_secret.encode("utf-8"), api_key.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac_sha256${digest}"


def verify_integration_api_key(api_key: str, api_key_hash: str) -> bool:
    return hmac.compare_digest(hash_integration_api_key(api_key), api_key_hash)


def authenticate_integration_client(db: Session, api_key: str) -> IntegrationClient | None:
    clients = db.scalars(select(IntegrationClient).where(IntegrationClient.is_active.is_(True))).all()
    for client in clients:
        if verify_integration_api_key(api_key, client.api_key_hash):
            client.last_used_at = datetime.utcnow()
            db.flush()
            return client
    return None


def require_scope(context: IntegrationContext, scope: str) -> None:
    if scope not in (context.client.scopes_json or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Integration client lacks {scope} scope")


def get_integration_context(
    db: Session = Depends(get_db),
    api_key: str | None = Header(default=None, alias="X-DocuIntel-API-Key"),
    technician_id: str | None = Header(default=None, alias="X-Technician-Id"),
    technician_name: str | None = Header(default=None, alias="X-Technician-Name"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> IntegrationContext:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing integration API key")
    if not technician_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing technician id")
    client = authenticate_integration_client(db, api_key)
    if not client:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration API key")
    enforce_integration_rate_limit(client_id=client.id, technician_id=technician_id)
    policy = resolve_access_policy(db, technician_id)
    access_scope = resolve_technician_access_scope(db, technician_id)
    budget_session = _decode_optional_budget_session(
        authorization=authorization,
        client_id=client.id,
        technician_id=technician_id,
    )
    return IntegrationContext(
        client=client,
        technician_id=technician_id,
        technician_name=technician_name,
        policy=policy,
        access_scope=access_scope,
        budget_session=budget_session,
    )


def _decode_optional_budget_session(
    *,
    authorization: str | None,
    client_id: int,
    technician_id: str,
) -> BudgetSessionClaims | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration session authorization")
    try:
        claims = decode_budget_session_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration session token") from exc
    if claims.client_id != client_id or claims.technician_id != technician_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Integration session does not match caller")
    return claims
