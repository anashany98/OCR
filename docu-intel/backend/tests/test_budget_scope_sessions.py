from __future__ import annotations

import os
from collections.abc import Generator
from datetime import date
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

settings.database_url = "sqlite+pysqlite:///:memory:"

from app.api.router import api_router
from app.core.security import create_access_token, hash_password
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    AccessPolicy,
    ApiClientBudgetScope,
    Budget,
    BudgetLine,
    BudgetScope,
    Document,
    DocumentPage,
    IntegrationClient,
    TechnicianAccessProfile,
    User,
)
from app.services.access_policy import ensure_default_access_policies
from app.services.integration_security import hash_integration_api_key


def _test_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(api_router)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def _headers(
    *,
    technician_id: str = "tecnico-17",
    api_key: str = "secret-key",
    session_token: str | None = None,
) -> dict[str, str]:
    headers = {"X-DocuIntel-API-Key": api_key, "X-Technician-Id": technician_id}
    if session_token:
        headers["Authorization"] = f"Bearer {session_token}"
    return headers


def _seed_base(session_factory: sessionmaker[Session]) -> dict[str, int]:
    with session_factory() as db:
        ensure_default_access_policies(db)
        client = IntegrationClient(
            name="external-tool",
            api_key_hash=hash_integration_api_key("secret-key"),
            scopes_json=["read", "upload"],
            is_active=True,
        )
        scope_a = BudgetScope(
            budget_code="245745",
            display_name="Presupuesto 245745",
            source_path="/srv/docuintel/inbox/245745",
            status="processed",
        )
        scope_b = BudgetScope(
            budget_code="484857",
            display_name="Presupuesto 484857",
            source_path="/srv/docuintel/inbox/484857",
            status="processed",
        )
        db.add_all([client, scope_a, scope_b])
        db.flush()
        db.add(
            ApiClientBudgetScope(
                api_client_id=client.id,
                budget_scope_id=scope_a.id,
                can_query=True,
                can_see_amounts=False,
            )
        )
        _add_budget(
            db,
            scope=scope_a,
            budget_number="2026/SAME",
            filename="scope-a.pdf",
            file_hash="a" * 64,
            client_name="Scope A",
            line_description="Linea Scope A",
        )
        _add_budget(
            db,
            scope=scope_b,
            budget_number="2026/SAME",
            filename="scope-b.pdf",
            file_hash="b" * 64,
            client_name="Scope B",
            line_description="Linea Scope B",
        )
        _add_budget(
            db,
            scope=scope_b,
            budget_number="2026/ONLY-B",
            filename="only-b.pdf",
            file_hash="c" * 64,
            client_name="Solo Scope B",
            line_description="Linea Solo B",
        )
        db.commit()
        return {"client_id": client.id, "scope_a_id": scope_a.id, "scope_b_id": scope_b.id}


def _add_budget(
    db: Session,
    *,
    scope: BudgetScope,
    budget_number: str,
    filename: str,
    file_hash: str,
    client_name: str,
    line_description: str,
) -> Budget:
    document = Document(
        budget_scope_id=scope.id,
        original_filename=filename,
        stored_filename=f"{file_hash[:2]}/{file_hash}.pdf",
        source_path=f"/srv/docuintel/inbox/{scope.budget_code}/{filename}",
        file_hash=file_hash,
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1200,
        document_type="presupuesto",
        status="processed",
        confidence=0.91,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=f"Presupuesto {budget_number} {client_name} Total 1.245,60 € precio unitario 22,50 €",
            ocr_confidence=0.91,
        )
    )
    budget = Budget(
        document_id=document.id,
        budget_number=budget_number,
        client_name=client_name,
        date=date(2026, 5, 15),
        total_amount=1245.60,
        currency="EUR",
        status="aceptado",
        accepted_detected=True,
        confidence=0.91,
    )
    db.add(budget)
    db.flush()
    db.add(
        BudgetLine(
            budget_id=budget.id,
            reference="ABC123",
            description=line_description,
            quantity=2,
            unit="ud",
            unit_price=22.50,
            total_price=45.00,
            confidence=0.90,
        )
    )
    return budget


def _create_session(client: TestClient, budget_code: str, technician_id: str = "tecnico-17") -> str:
    response = client.post(
        "/integrations/v1/sessions",
        headers=_headers(technician_id=technician_id),
        json={"budget_code": budget_code},
    )
    assert response.status_code == 200
    return response.json()["session_token"]


def _admin_token(db: Session) -> str:
    user = User(
        email="admin@local",
        name="Admin",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return create_access_token(str(user.id))


def test_session_requires_explicit_budget_scope_permission():
    client, sessions = _test_client()
    _seed_base(sessions)

    denied = client.post(
        "/integrations/v1/sessions",
        headers=_headers(),
        json={"budget_code": "484857"},
    )
    allowed = client.post(
        "/integrations/v1/sessions",
        headers=_headers(),
        json={"budget_code": "245745"},
    )

    assert denied.status_code == 403
    assert "budget scope" in denied.json()["detail"].lower()
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["budget_code"] == "245745"
    assert payload["budget_scope_id"] > 0
    assert payload["session_token"]
    assert payload["can_see_amounts"] is False


def test_session_token_filters_budget_lookup_to_one_scope():
    client, sessions = _test_client()
    _seed_base(sessions)
    session_token = _create_session(client, "245745")

    same_number = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(session_token=session_token),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/SAME"}},
    )
    outside_scope = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(session_token=session_token),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/ONLY-B"}},
    )

    assert same_number.status_code == 200
    payload = same_number.json()
    assert payload["data"]["budget_number"] == "2026/SAME"
    assert payload["data"]["client_name"] == "Scope A"
    assert payload["data"]["lines"][0]["description"] == "Linea Scope A"
    assert payload["scope"]["budget_code"] == "245745"
    assert "Scope B" not in str(payload)
    assert outside_scope.status_code == 200
    assert outside_scope.json()["data"]["status"] == "not_found"
    assert "Solo Scope B" not in str(outside_scope.json())


def test_session_permission_hides_prices_even_for_price_policy():
    client, sessions = _test_client()
    _seed_base(sessions)
    with sessions() as db:
        policy = db.scalar(select(AccessPolicy).where(AccessPolicy.name == "precios_autorizados"))
        db.add(TechnicianAccessProfile(technician_id="jefe-1", technician_name="Jefe", access_policy_id=policy.id))
        db.commit()
    session_token = _create_session(client, "245745", technician_id="jefe-1")

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(technician_id="jefe-1", session_token=session_token),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/SAME"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "total_amount" not in payload["data"]
    assert "currency" not in payload["data"]
    assert "unit_price" not in payload["data"]["lines"][0]
    assert "total_price" not in payload["data"]["lines"][0]
    assert "1.245,60" not in str(payload)
    assert "22,50" not in str(payload)
    assert "[IMPORTE OCULTO]" in payload["sources"][0]["excerpt"]
    assert "budget.total_amount" in payload["redactions"]


def test_admin_can_create_budget_scope_and_grant_client_permission():
    client, sessions = _test_client()
    seeded = _seed_base(sessions)
    with sessions() as db:
        token = _admin_token(db)
        db.commit()

    create_scope = client.post(
        "/admin/budget-scopes",
        headers={"Authorization": f"Bearer {token}"},
        json={"budget_code": "999001", "display_name": "Presupuesto 999001"},
    )
    assert create_scope.status_code == 200
    scope_payload = create_scope.json()
    assert scope_payload["budget_code"] == "999001"

    grant = client.post(
        f"/admin/budget-scopes/{scope_payload['id']}/client-permissions",
        headers={"Authorization": f"Bearer {token}"},
        json={"client_id": seeded["client_id"], "can_query": True, "can_see_amounts": False},
    )
    assert grant.status_code == 200
    assert grant.json()["can_query"] is True
    assert grant.json()["can_see_amounts"] is False

    session_response = client.post(
        "/integrations/v1/sessions",
        headers=_headers(),
        json={"budget_code": "999001"},
    )
    assert session_response.status_code == 200
