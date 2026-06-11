from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import (
    ApiClientBudgetScope,
    BudgetScope,
    IntegrationClient,
    User,
)
from app.schemas.admin import (
    ApiClientBudgetScopeRead,
    ApiClientBudgetScopeUpsert,
    BudgetScopeCreate,
    BudgetScopeRead,
    IntegrationClientCreate,
    IntegrationClientRead,
    IntegrationClientSecretRead,
    IntegrationClientUpdate,
    IntegrationSandboxExecuteRequest,
)
from app.services.audit import write_audit
from app.services.access_policy import resolve_access_policy, policy_allows_prices
from app.services.budget_scope import ensure_budget_scope
from app.services.integration_security import IntegrationContext, hash_integration_api_key
from app.services.integration_tools import execute_integration_tool
from app.services.tenant_access import resolve_technician_access_scope

from app.api.routes.admin_helpers import _get_or_404, _new_api_key, _normalize_scopes

router = APIRouter(prefix="/admin")


# ---------- budget scopes ----------

@router.get("/budget-scopes", response_model=list[BudgetScopeRead])
def list_budget_scopes(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[BudgetScope]:
    stmt = select(BudgetScope).order_by(BudgetScope.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where((BudgetScope.budget_code.ilike(pattern)) | (BudgetScope.display_name.ilike(pattern)))
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


@router.post("/budget-scopes", response_model=BudgetScopeRead)
def create_budget_scope(
    payload: BudgetScopeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> BudgetScope:
    scope = ensure_budget_scope(db, payload.budget_code, source_path=payload.source_path)
    scope.local_path = payload.local_path
    scope.display_name = payload.display_name or scope.display_name
    scope.status = payload.status
    write_audit(db, user=user, action="budget_scope_upserted", entity_type="budget_scope", entity_id=scope.id)
    db.commit()
    db.refresh(scope)
    return scope


@router.get("/budget-scopes/{scope_id}/client-permissions", response_model=list[ApiClientBudgetScopeRead])
def list_budget_scope_client_permissions(
    scope_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
) -> list[ApiClientBudgetScope]:
    _get_or_404(db, BudgetScope, scope_id, "Budget scope not found")
    return list(
        db.scalars(
            select(ApiClientBudgetScope)
            .where(ApiClientBudgetScope.budget_scope_id == scope_id)
            .order_by(ApiClientBudgetScope.id.asc())
        ).all()
    )


@router.post("/budget-scopes/{scope_id}/client-permissions", response_model=ApiClientBudgetScopeRead)
def upsert_budget_scope_client_permission(
    scope_id: int,
    payload: ApiClientBudgetScopeUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> ApiClientBudgetScope:
    _get_or_404(db, BudgetScope, scope_id, "Budget scope not found")
    _get_or_404(db, IntegrationClient, payload.client_id, "Integration client not found")
    permission = db.scalar(
        select(ApiClientBudgetScope)
        .where(ApiClientBudgetScope.budget_scope_id == scope_id)
        .where(ApiClientBudgetScope.api_client_id == payload.client_id)
    )
    if not permission:
        permission = ApiClientBudgetScope(api_client_id=payload.client_id, budget_scope_id=scope_id)
        db.add(permission)
        db.flush()
    permission.can_query = payload.can_query
    permission.can_see_amounts = payload.can_see_amounts
    write_audit(
        db,
        user=user,
        action="budget_scope_client_permission_upserted",
        entity_type="budget_scope",
        entity_id=scope_id,
        details={
            "api_client_id": payload.client_id,
            "can_query": payload.can_query,
            "can_see_amounts": payload.can_see_amounts,
        },
    )
    db.commit()
    db.refresh(permission)
    return permission


# ---------- integration clients ----------

@router.get("/integration-clients", response_model=list[IntegrationClientRead])
def list_integration_clients(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
) -> list[IntegrationClient]:
    return list(db.scalars(select(IntegrationClient).order_by(IntegrationClient.name.asc())).all())


@router.post("/integration-clients", response_model=IntegrationClientSecretRead)
def create_integration_client(
    payload: IntegrationClientCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> IntegrationClientSecretRead:
    existing = db.scalar(select(IntegrationClient).where(IntegrationClient.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Integration client name already exists")
    api_key = _new_api_key()  # SEC-APIKEY-1: returns "kid_xxx.<secret>"
    key_id, _, _secret = api_key.partition(".")
    client = IntegrationClient(
        name=payload.name,
        key_id=key_id,
        api_key_hash=hash_integration_api_key(api_key),
        scopes_json=_normalize_scopes(payload.scopes),
        is_active=payload.is_active,
    )
    db.add(client)
    db.flush()
    write_audit(
        db,
        user=user,
        action="integration_client_created",
        entity_type="integration_client",
        entity_id=client.id,
        details={"name": client.name, "scopes": client.scopes_json},
    )
    db.commit()
    db.refresh(client)
    return IntegrationClientSecretRead.model_validate(client, from_attributes=True).model_copy(update={"api_key": api_key})


@router.patch("/integration-clients/{client_id}", response_model=IntegrationClientRead)
def update_integration_client(
    client_id: int,
    payload: IntegrationClientUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> IntegrationClient:
    client = _get_or_404(db, IntegrationClient, client_id, "Integration client not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != client.name:
        existing = db.scalar(select(IntegrationClient).where(IntegrationClient.name == data["name"]))
        if existing:
            raise HTTPException(status_code=409, detail="Integration client name already exists")
        client.name = data["name"]
    if "scopes" in data and data["scopes"] is not None:
        client.scopes_json = _normalize_scopes(data["scopes"])
    if "is_active" in data and data["is_active"] is not None:
        client.is_active = bool(data["is_active"])
    write_audit(
        db,
        user=user,
        action="integration_client_updated",
        entity_type="integration_client",
        entity_id=client.id,
        details={"name": client.name, "scopes": client.scopes_json, "is_active": client.is_active},
    )
    db.commit()
    db.refresh(client)
    return client


@router.post("/integration-clients/{client_id}/rotate-key", response_model=IntegrationClientSecretRead)
def rotate_integration_client_key(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> IntegrationClientSecretRead:
    client = _get_or_404(db, IntegrationClient, client_id, "Integration client not found")
    api_key = _new_api_key()  # SEC-APIKEY-1: "kid_xxx.<secret>"
    key_id, _, _secret = api_key.partition(".")
    client.key_id = key_id
    client.api_key_hash = hash_integration_api_key(api_key)
    write_audit(
        db,
        user=user,
        action="integration_client_key_rotated",
        entity_type="integration_client",
        entity_id=client.id,
        details={"name": client.name},
    )
    db.commit()
    db.refresh(client)
    return IntegrationClientSecretRead.model_validate(client, from_attributes=True).model_copy(update={"api_key": api_key})


# ---------- sandbox ----------

@router.post("/integration-sandbox/execute")
def integration_sandbox_execute(
    payload: IntegrationSandboxExecuteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    client = _get_or_404(db, IntegrationClient, payload.client_id, "Integration client not found")
    if not client.is_active:
        raise HTTPException(status_code=409, detail="Integration client is inactive")
    policy = resolve_access_policy(db, payload.technician_id)
    access_scope = resolve_technician_access_scope(db, payload.technician_id)
    access_scope.allow_unassigned_documents = True
    context = IntegrationContext(
        client=client,
        technician_id=payload.technician_id,
        technician_name=payload.technician_name,
        policy=policy,
        access_scope=access_scope,
        budget_session=None,
    )
    response = execute_integration_tool(db, context=context, tool=payload.tool, arguments=payload.arguments)
    response.warnings.append("Sandbox: respuesta de prueba generada desde administracion, sin afectar produccion.")
    write_audit(
        db,
        user=user,
        action="admin_integration_sandbox_execute",
        entity_type="integration_client",
        entity_id=client.id,
        details={
            "technician_id": payload.technician_id,
            "tool": payload.tool,
            "arguments": payload.arguments,
            "request_id": response.request_id,
            "redactions": response.redactions,
        },
    )
    db.commit()
    return response
