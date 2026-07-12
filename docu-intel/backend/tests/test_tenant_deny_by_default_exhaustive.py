"""Integration contract for deny-by-default access across business resources.

The previous version was a permanently skipped placeholder whose URLs and
resource identifiers did not match the API.  These tests use the real router,
two scoped hotels, and a foreign resource of every supported business kind.
"""
from __future__ import annotations

import os
from collections.abc import Generator
from datetime import date

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    AccessGroup,
    AccessGroupMember,
    Budget,
    Document,
    DocumentAccessMetadata,
    Hotel,
    HotelChain,
    Invoice,
    Order,
    Plan,
    User,
)


@pytest.fixture
def client_and_session() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(api_router)

    def override_get_db() -> Generator[Session, None, None]:
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    old_database_url = settings.database_url
    settings.database_url = "sqlite+pysqlite:///:memory:"
    try:
        yield TestClient(app), sessions
    finally:
        settings.database_url = old_database_url
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def two_tenants(client_and_session: tuple[TestClient, sessionmaker[Session]]) -> dict[str, object]:
    client, sessions = client_and_session
    with sessions() as db:
        chain_a = HotelChain(name="Cadena autorizada", is_active=True)
        chain_b = HotelChain(name="Cadena ajena", is_active=True)
        db.add_all([chain_a, chain_b])
        db.flush()
        hotel_a = Hotel(chain_id=chain_a.id, name="Hotel autorizado", code="AUTH", is_active=True)
        hotel_b = Hotel(chain_id=chain_b.id, name="Hotel ajeno", code="FOREIGN", is_active=True)
        db.add_all([hotel_a, hotel_b])
        db.flush()

        user = User(
            email="gestor-hotel-a@local",
            name="Gestor Hotel A",
            password_hash=hash_password("secret"),
            role="gestor",
            is_active=True,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Gestores Hotel autorizado",
            permissions_json={
                "chain_ids": [],
                "hotel_ids": [hotel_a.id],
                "allow_all_hotels": False,
                "allow_unassigned_documents": False,
                "denied_tags": [],
                "can_view_prices": True,
                "can_search_budgets": True,
            },
            is_active=True,
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))

        foreign_document = Document(
            original_filename="SECRETO-HOTEL-B.pdf",
            stored_filename="foreign/secret.pdf",
            source_path="/source/foreign/SECRETO-HOTEL-B.pdf",
            file_hash="f" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=128,
            document_type="presupuesto",
            status="processed",
            page_count=1,
        )
        db.add(foreign_document)
        db.flush()
        db.add(
            DocumentAccessMetadata(
                document_id=foreign_document.id,
                chain_id=chain_b.id,
                hotel_id=hotel_b.id,
                assignment_status="assigned",
                assignment_source="test",
                tags_json=[],
            )
        )
        foreign_budget = Budget(
            document_id=foreign_document.id,
            budget_number="FOREIGN-BUDGET-2026",
            client_name=hotel_b.name,
            date=date(2026, 7, 1),
            total_amount=9999.0,
            currency="EUR",
            confidence=1.0,
        )
        foreign_order = Order(
            document_id=foreign_document.id,
            order_number="FOREIGN-ORDER-2026",
            supplier_name="Proveedor ajeno",
            client_name=hotel_b.name,
            date=date(2026, 7, 1),
            total_amount=9999.0,
            currency="EUR",
            confidence=1.0,
        )
        foreign_invoice = Invoice(
            document_id=foreign_document.id,
            invoice_number="FOREIGN-INVOICE-2026",
            supplier_name="Proveedor ajeno",
            client_name=hotel_b.name,
            date=date(2026, 7, 1),
            total_amount=9999.0,
            currency="EUR",
            confidence=1.0,
        )
        foreign_plan = Plan(document_id=foreign_document.id, project_name="Plano secreto")
        db.add_all([foreign_budget, foreign_order, foreign_invoice, foreign_plan])
        db.commit()

        return {
            "client": client,
            "headers": {"Authorization": f"Bearer {create_access_token(str(user.id))}"},
            "document_id": foreign_document.id,
            "budget_id": foreign_budget.id,
            "order_id": foreign_order.id,
            "invoice_id": foreign_invoice.id,
            "plan_id": foreign_plan.id,
        }


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("GET", "/documents/{document_id}"),
        ("GET", "/documents/{document_id}/pages"),
        ("GET", "/documents/{document_id}/blocks"),
        ("GET", "/documents/{document_id}/entities"),
        ("GET", "/documents/{document_id}/download"),
        ("POST", "/documents/{document_id}/reprocess?mode=text"),
        ("GET", "/budgets/{budget_id}"),
        ("GET", "/budgets/{budget_id}/lines"),
        ("GET", "/orders/{order_id}"),
        ("GET", "/orders/{order_id}/lines"),
        ("GET", "/plans/{plan_id}"),
        ("GET", "/plans/{plan_id}/rooms"),
        ("GET", "/plans/{plan_id}/dimensions"),
        ("GET", "/plans/{plan_id}/symbols"),
        ("GET", "/plans/{plan_id}/symbols/summary"),
    ],
)
def test_cross_tenant_detail_routes_hide_foreign_resources(
    two_tenants: dict[str, object], method: str, path_template: str
) -> None:
    client = two_tenants["client"]
    assert isinstance(client, TestClient)
    response = client.request(
        method,
        path_template.format(**two_tenants),
        headers=two_tenants["headers"],
    )

    assert response.status_code == 404
    assert "SECRETO-HOTEL-B" not in response.text
    assert "9999" not in response.text


@pytest.mark.parametrize("path", ["/documents", "/budgets", "/orders", "/invoices", "/plans"])
def test_cross_tenant_collections_do_not_list_foreign_resources(
    two_tenants: dict[str, object], path: str
) -> None:
    client = two_tenants["client"]
    assert isinstance(client, TestClient)
    response = client.get(path, headers=two_tenants["headers"])

    assert response.status_code == 200
    assert "SECRETO-HOTEL-B" not in response.text
    assert "FOREIGN-" not in response.text
    assert "9999" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/invoices/aggregate/monthly?year=2026",
        "/invoices/aggregate/by-supplier?year=2026",
        "/invoices/aggregate/yearly",
    ],
)
def test_invoice_aggregates_exclude_foreign_tenant(two_tenants: dict[str, object], path: str) -> None:
    client = two_tenants["client"]
    assert isinstance(client, TestClient)
    response = client.get(path, headers=two_tenants["headers"])

    assert response.status_code == 200
    assert response.json() == []
    assert "9999" not in response.text
