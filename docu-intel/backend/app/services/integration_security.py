"""Integration API key authentication (SEC-APIKEY-1 / Sprint 1).

The previous implementation authenticated every integration request
with a full table scan of ``integration_clients``:

    db.scalars(select(IntegrationClient).where(is_active=True)).all()
    for client in clients:
        if verify_integration_api_key(api_key, client.api_key_hash):
            client.last_used_at = datetime.utcnow()
            db.flush()
            return client

Two problems with this design:

1. **O(n) lookup**: every request scanned every active client and
   computed an HMAC against each one. With hundreds of clients this
   dominated the auth latency.
2. **Write storm on ``last_used_at``**: every successful auth issued
   an UPDATE on the matched row. With dozens of req/min per client
   this is hundreds of writes per minute on a hot table — and the
   ``db.flush()`` inside the auth function meant a write happened
   even on read-only ``GET /manifest`` calls.

The fix:

* Add a public ``key_id`` column to ``integration_clients`` (one
  ``kid_`` + 16 hex chars). The client sends it in
  ``X-DocuIntel-Key-Id`` and the secret in ``X-DocuIntel-Key-Secret``.
  Lookup is now O(1) via the unique index.
* Throttle ``last_used_at`` updates to at most one per minute per
  client. Implemented with a process-local dict (the value is also
  good enough for an admin dashboard; if a multi-process deployment
  needs stricter freshness, swap for Redis).
* Keep the legacy ``X-DocuIntel-API-Key`` header working for one
  release (deprecated path) so existing integrations have time to
  rotate. The legacy path keeps its O(n) cost.

The public surface for callers is unchanged: ``get_integration_context``
still returns an :class:`IntegrationContext`. The only thing that
moves is how the client is identified.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
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


# Process-local throttle for ``last_used_at`` updates. A multi-worker
# deployment can have N workers; this dict is Nx the writes we'd
# otherwise have (one per request) but still orders of magnitude less
# than a write per request. Keys are ``client.id``; values are
# monotonic timestamps (monotonic from :func:`time.monotonic`).
_LAST_USED_SEEN: dict[int, float] = {}
_LAST_USED_LOCK = threading.Lock()
_LAST_USED_TTL_SECONDS = 60  # 1 update per minute per client


@dataclass
class IntegrationContext:
    client: IntegrationClient
    technician_id: str
    technician_name: str | None
    policy: AccessPolicy
    access_scope: AccessScope
    budget_session: BudgetSessionClaims | None = None


def hash_integration_api_key(api_key: str) -> str:
    # AUTH-JWT-1 (Sprint 1): use a dedicated HMAC secret for API
    # key hashing so a leak of the user JWT secret cannot be used
    # to forge or brute-force API key hashes. Falls back to
    # ``jwt_secret`` for backward compatibility.
    from app.core.security import _api_key_hmac_secret  # local import: avoids circular
    digest = hmac.new(
        _api_key_hmac_secret().encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac_sha256${digest}"


def verify_integration_api_key(api_key: str, api_key_hash: str) -> bool:
    return hmac.compare_digest(hash_integration_api_key(api_key), api_key_hash)


def generate_api_key() -> str:
    """Generate a fresh, unguessable API key for a new client.

    The key is 256 bits of entropy encoded as URL-safe base64
    (44 chars). The client receives it once; only its HMAC is
    stored.
    """
    import secrets
    return secrets.token_urlsafe(32)


def generate_key_id() -> str:
    """Generate a public, random ``kid_`` + 16 hex chars identifier.

    Used as the O(1) lookup key in the ``key_id`` column. Distinct
    from the secret so a leak of the ``key_id`` does not reveal the
    secret.
    """
    import secrets
    return "kid_" + secrets.token_hex(8)


def _mark_used_throttled(client: IntegrationClient) -> None:
    """Update ``client.last_used_at`` at most once per minute per id.

    The throttle is per-process. With ``WORKER_FAST_CONCURRENCY=4``
    and 50 active clients doing 1 req/s each, the per-process rate
    is still bounded so the write amplification is at most
    ``active_clients * 60 * workers`` per hour — a few hundred,
    not a few thousand.
    """
    now = time.monotonic()
    with _LAST_USED_LOCK:
        last = _LAST_USED_SEEN.get(client.id, 0.0)
        if now - last < _LAST_USED_TTL_SECONDS:
            return
        _LAST_USED_SEEN[client.id] = now
    client.last_used_at = datetime.utcnow()
    # Caller is responsible for ``db.commit()`` at the end of the
    # request so the throttle is transactional.


def reset_last_used_throttle() -> None:
    """Test helper: forget all throttled timestamps."""
    with _LAST_USED_LOCK:
        _LAST_USED_SEEN.clear()


def authenticate_integration_client_by_key_id(
    db: Session, key_id: str, secret: str
) -> IntegrationClient | None:
    """O(1) lookup by ``key_id`` followed by HMAC verification.

    The combination of a public ``key_id`` and a private secret is
    the standard model (AWS access keys, Stripe secret keys, etc.):
    the ``key_id`` is safe to log; the secret is verified out-of-band.

    Returns the matched client (with ``last_used_at`` throttled) or
    ``None``. Never raises; the caller turns ``None`` into 401.
    """
    if not key_id or not secret:
        return None
    client = db.scalar(
        select(IntegrationClient).where(
            IntegrationClient.key_id == key_id,
            IntegrationClient.is_active.is_(True),
        )
    )
    if client is None:
        return None
    if not verify_integration_api_key(secret, client.api_key_hash):
        return None
    _mark_used_throttled(client)
    return client


def authenticate_integration_client_legacy(
    db: Session, api_key: str
) -> IntegrationClient | None:
    """Backward-compat path: legacy clients that still send the full
    key in ``X-DocuIntel-API-Key``.

    **O(n) and write-amplifying** by design. Kept for one release so
    existing integrations have time to rotate. Will be removed in the
    next major version; operators should run a "rotate key" job for
    every active integration client before then.
    """
    if not api_key:
        return None
    clients = db.scalars(
        select(IntegrationClient).where(IntegrationClient.is_active.is_(True))
    ).all()
    for client in clients:
        if verify_integration_api_key(api_key, client.api_key_hash):
            _mark_used_throttled(client)
            return client
    return None


def authenticate_integration_client(
    db: Session, api_key: str
) -> IntegrationClient | None:
    """Deprecated: kept as a thin shim for the old call signature."""
    return authenticate_integration_client_legacy(db, api_key)


def require_scope(context: IntegrationContext, scope: str) -> None:
    if scope not in (context.client.scopes_json or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Integration client lacks {scope} scope")


def get_integration_context(
    db: Session = Depends(get_db),
    # New (preferred) auth headers (SEC-APIKEY-1):
    api_key_id: str | None = Header(default=None, alias="X-DocuIntel-Key-Id"),
    api_key_secret: str | None = Header(default=None, alias="X-DocuIntel-Key-Secret"),
    # Legacy auth header (one-release deprecation window):
    api_key: str | None = Header(default=None, alias="X-DocuIntel-API-Key"),
    technician_id: str | None = Header(default=None, alias="X-Technician-Id"),
    technician_name: str | None = Header(default=None, alias="X-Technician-Name"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> IntegrationContext:
    if not technician_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing technician id")

    # New path: X-DocuIntel-Key-Id + X-DocuIntel-Key-Secret.
    if api_key_id and api_key_secret:
        client = authenticate_integration_client_by_key_id(
            db, api_key_id, api_key_secret
        )
    elif api_key:
        # Legacy path: X-DocuIntel-API-Key=<secret>.
        client = authenticate_integration_client_legacy(db, api_key)
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing integration API key (X-DocuIntel-Key-Id + X-DocuIntel-Key-Secret, or X-DocuIntel-API-Key)",
        )

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


__all__ = [
    "IntegrationContext",
    "hash_integration_api_key",
    "verify_integration_api_key",
    "authenticate_integration_client_by_key_id",
    "authenticate_integration_client_legacy",
    "authenticate_integration_client",
    "require_scope",
    "get_integration_context",
    "generate_api_key",
    "generate_key_id",
    "reset_last_used_throttle",
]
