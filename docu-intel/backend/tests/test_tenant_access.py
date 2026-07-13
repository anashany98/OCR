from __future__ import annotations

import os
from collections.abc import Generator
from datetime import date
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi import FastAPI
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.core.config import settings

settings.database_url = "sqlite+pysqlite:///:memory:"

from app.api.router import api_router
from app.core.security import create_access_token, hash_password
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    AccessGroup,
    AccessGroupMember,
    AccessPolicy,
    Budget,
    BudgetLine,
    Document,
    DocumentAccessMetadata,
    DocumentPage,
    FolderAssignmentRule,
    Hotel,
    HotelChain,
    Invoice,
    IntegrationClient,
    Order,
    OrderLine,
    ReconciliationIssue,
    User,
)
from app.services.access_policy import ensure_default_access_policies
from app.services.integration_security import hash_integration_api_key
from app.services.tenant_access import AccessScope, apply_folder_rules_to_document
from app.tools import internal


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


def _headers(technician_id: str = "tech-a") -> dict[str, str]:
    return {"X-DocuIntel-API-Key": "secret-key", "X-Technician-Id": technician_id}


def _seed_base(db: Session) -> dict[str, object]:
    ensure_default_access_policies(db)
    db.add(
        IntegrationClient(
            name="external-tool",
            api_key_hash=hash_integration_api_key("secret-key"),
            scopes_json=["read", "upload"],
            is_active=True,
        )
    )
    chain_a = HotelChain(name="Cadena A", is_active=True)
    chain_b = HotelChain(name="Cadena B", is_active=True)
    db.add_all([chain_a, chain_b])
    db.flush()
    hotel_a = Hotel(chain_id=chain_a.id, name="Hotel A", code="A", is_active=True)
    hotel_b = Hotel(chain_id=chain_b.id, name="Hotel B", code="B", is_active=True)
    db.add_all([hotel_a, hotel_b])
    db.flush()
    db.add(
        AccessGroup(
            name="Tecnicos Hotel A",
            permissions_json={
                "chain_ids": [],
                "hotel_ids": [hotel_a.id],
                "allow_all_hotels": False,
                "denied_tags": [],
                "can_view_prices": False,
                "can_search_budgets": True,
            },
        )
    )
    db.flush()
    group = db.scalar(select(AccessGroup).where(AccessGroup.name == "Tecnicos Hotel A"))
    db.add(AccessGroupMember(group_id=group.id, principal_type="technician", principal_id="tech-a"))
    db.commit()
    return {"chain_a": chain_a, "chain_b": chain_b, "hotel_a": hotel_a, "hotel_b": hotel_b}


def _add_budget(
    db: Session,
    *,
    budget_number: str,
    hotel: Hotel,
    chain: HotelChain,
    filename: str,
    file_hash: str,
    tags: list[str] | None = None,
) -> Budget:
    document = Document(
        original_filename=filename,
        stored_filename=f"{file_hash[:2]}/{file_hash}.pdf",
        source_path=f"/data/input/presupuestos/{chain.name}/{hotel.name}/{filename}",
        file_hash=file_hash,
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1200,
        document_type="presupuesto",
        status="processed",
        confidence=0.9,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentAccessMetadata(
            document_id=document.id,
            chain_id=chain.id,
            hotel_id=hotel.id,
            assignment_status="assigned",
            assignment_source="manual",
            tags_json=tags or [],
        )
    )
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=f"Presupuesto {budget_number} {hotel.name} Total 9.999,00 € referencia ABC123",
            ocr_confidence=0.9,
        )
    )
    budget = Budget(
        document_id=document.id,
        budget_number=budget_number,
        client_name=hotel.name,
        date=date(2026, 5, 14),
        total_amount=9999.0,
        currency="EUR",
        status="aceptado",
        accepted_detected=True,
        confidence=0.9,
    )
    db.add(budget)
    db.flush()
    db.add(
        BudgetLine(
            budget_id=budget.id,
            reference="ABC123",
            description=f"Linea {hotel.name}",
            quantity=1,
            unit="ud",
            unit_price=9999.0,
            total_price=9999.0,
            confidence=0.9,
        )
    )
    db.commit()
    return budget


def test_external_technician_cannot_access_budget_from_other_hotel():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        _add_budget(
            db,
            budget_number="2026/A",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="presupuesto-a.pdf",
            file_hash="a" * 64,
        )
        _add_budget(
            db,
            budget_number="2026/B",
            hotel=seeded["hotel_b"],
            chain=seeded["chain_b"],
            filename="presupuesto-b.pdf",
            file_hash="b" * 64,
        )

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/B"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "not_found"
    assert payload["sources"] == []
    assert "Hotel B" not in str(payload)


def test_quarantined_document_is_not_returned_to_integration_search():
    client, sessions = _test_client()
    with sessions() as db:
        _seed_base(db)
        document = Document(
            original_filename="sin-asignar.pdf",
            stored_filename="cc/sin-asignar.pdf",
            source_path="/data/input/otros/sin-asignar.pdf",
            file_hash="c" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=500,
            document_type="presupuesto",
            status="processed",
            page_count=1,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentAccessMetadata(
                document_id=document.id,
                assignment_status="quarantine",
                assignment_source="none",
                tags_json=[],
            )
        )
        db.add(DocumentPage(document_id=document.id, page_number=1, text="Referencia SECRETO-Q", ocr_confidence=0.9))
        db.commit()

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "search_documents", "arguments": {"query": "SECRETO-Q", "limit": 10}},
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["sources"] == []


def test_same_budget_number_inside_authorized_scope_returns_conflict():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        hotel_a2 = Hotel(chain_id=seeded["chain_a"].id, name="Hotel A2", code="A2", is_active=True)
        db.add(hotel_a2)
        db.flush()
        group = db.scalar(select(AccessGroup).where(AccessGroup.name == "Tecnicos Hotel A"))
        group.permissions_json = {
            "chain_ids": [],
            "hotel_ids": [seeded["hotel_a"].id, hotel_a2.id],
            "allow_all_hotels": False,
            "denied_tags": [],
            "can_view_prices": False,
            "can_search_budgets": True,
        }
        _add_budget(
            db,
            budget_number="2026/777",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="presupuesto-777-a.pdf",
            file_hash="d" * 64,
        )
        _add_budget(
            db,
            budget_number="2026/777",
            hotel=hotel_a2,
            chain=seeded["chain_a"],
            filename="presupuesto-777-a2.pdf",
            file_hash="e" * 64,
        )

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/777"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "conflict"
    assert payload["data"]["matches"] == 2
    assert any("conflicto" in warning.lower() or "mismo numero" in warning.lower() for warning in payload["warnings"])


def test_internal_user_with_denied_tag_cannot_see_accounting_document():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        user = User(
            email="gestor@local",
            name="Gestor",
            password_hash=hash_password("secret"),
            role="gestor",
            is_active=True,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Gestores sin contabilidad",
            permissions_json={
                "chain_ids": [],
                "hotel_ids": [],
                "allow_all_hotels": True,
                "denied_tags": ["contabilidad"],
                "can_view_prices": True,
                "can_search_budgets": True,
            },
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))
        visible = _add_budget(
            db,
            budget_number="2026/VISIBLE",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="visible.pdf",
            file_hash="f" * 64,
        )
        hidden = _add_budget(
            db,
            budget_number="2026/HIDDEN",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="contabilidad.pdf",
            file_hash="1" * 64,
            tags=["contabilidad"],
        )
        db.commit()
        token = create_access_token(str(user.id))

    response = client.get("/documents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    filenames = {item["original_filename"] for item in response.json()}
    assert "visible.pdf" in filenames
    assert "contabilidad.pdf" not in filenames


def test_admin_can_list_quarantine_documents():
    client, sessions = _test_client()
    with sessions() as db:
        _seed_base(db)
        admin = User(
            email="admin@local",
            name="Admin",
            password_hash=hash_password("secret"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        document = Document(
            original_filename="cuarentena.pdf",
            stored_filename="22/cuarentena.pdf",
            source_path="/data/input/otros/cuarentena.pdf",
            file_hash="2" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=500,
            document_type="desconocido",
            status="processed",
        )
        db.add(document)
        db.flush()
        db.add(DocumentAccessMetadata(document_id=document.id, assignment_status="quarantine", assignment_source="none"))
        db.commit()
        token = create_access_token(str(admin.id))

    response = client.get("/admin/quarantine-documents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert any(item["original_filename"] == "cuarentena.pdf" for item in response.json())


def test_admin_can_list_documents_without_server_error():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        admin = User(
            email="admin@local",
            name="Admin",
            password_hash=hash_password("secret"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        _add_budget(
            db,
            budget_number="2026/LIST",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="listado.pdf",
            file_hash="5" * 64,
        )
        db.commit()
        token = create_access_token(str(admin.id))

    response = client.get("/documents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert any(item["original_filename"] == "listado.pdf" for item in response.json())


def test_business_routes_hide_price_fields_without_price_permission():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        user = User(
            email="operario@local",
            name="Operario",
            password_hash=hash_password("secret"),
            role="operario",
            is_active=True,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Operario Hotel A sin precios",
            permissions_json={
                "chain_ids": [],
                "hotel_ids": [seeded["hotel_a"].id],
                "allow_all_hotels": False,
                "denied_tags": [],
                "can_view_prices": False,
                "can_search_budgets": True,
            },
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))
        budget = _add_budget(
            db,
            budget_number="2026/NO-PRICES",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="sin-precios.pdf",
            file_hash="8" * 64,
        )
        order = Order(
            document_id=budget.document_id,
            order_number="P-PRICE",
            supplier_name="Proveedor",
            client_name="Hotel A",
            date=date(2026, 5, 14),
            total_amount=9999.0,
            currency="EUR",
            confidence=0.9,
        )
        db.add(order)
        db.flush()
        db.add(
            OrderLine(
                order_id=order.id,
                reference="ORD1",
                description="Linea pedido",
                quantity=1,
                unit="ud",
                unit_price=9999.0,
                total_price=9999.0,
                confidence=0.9,
            )
        )
        invoice = Invoice(
            document_id=budget.document_id,
            invoice_number="F-PRICE",
            supplier_name="Proveedor",
            client_name="Hotel A",
            date=date(2026, 5, 14),
            total_amount=9999.0,
            currency="EUR",
            confidence=0.9,
        )
        db.add(invoice)
        db.commit()
        token = create_access_token(str(user.id))

    budgets_response = client.get("/budgets", headers={"Authorization": f"Bearer {token}"})
    lines_response = client.get(f"/budgets/{budget.id}/lines", headers={"Authorization": f"Bearer {token}"})
    orders_response = client.get("/orders", headers={"Authorization": f"Bearer {token}"})
    order_lines_response = client.get(f"/orders/{order.id}/lines", headers={"Authorization": f"Bearer {token}"})
    invoices_response = client.get("/invoices", headers={"Authorization": f"Bearer {token}"})

    assert budgets_response.status_code == 200
    budget_payload = next(item for item in budgets_response.json() if item["id"] == budget.id)
    assert budget_payload["total_amount"] is None
    assert budget_payload["currency"] is None
    assert "9999" not in str(budget_payload)
    assert lines_response.status_code == 200
    line_payload = lines_response.json()[0]
    assert line_payload["unit_price"] is None
    assert line_payload["total_price"] is None
    assert "9999" not in str(line_payload)
    assert orders_response.status_code == 200
    order_payload = next(item for item in orders_response.json() if item["id"] == order.id)
    assert order_payload["total_amount"] is None
    assert order_payload["currency"] is None
    assert "9999" not in str(order_payload)
    assert order_lines_response.status_code == 200
    order_line_payload = order_lines_response.json()[0]
    assert order_line_payload["unit_price"] is None
    assert order_line_payload["total_price"] is None
    assert "9999" not in str(order_line_payload)
    assert invoices_response.status_code == 200
    invoice_payload = next(item for item in invoices_response.json() if item["id"] == invoice.id)
    assert invoice_payload["total_amount"] is None
    assert invoice_payload["currency"] is None
    assert "9999" not in str(invoice_payload)


def test_ai_aggregate_business_is_scoped_and_hides_amounts_without_price_permission():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        _add_budget(
            db,
            budget_number="2026/A-SCOPED",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="scoped-a.pdf",
            file_hash="9" * 64,
        )
        _add_budget(
            db,
            budget_number="2026/B-HIDDEN",
            hotel=seeded["hotel_b"],
            chain=seeded["chain_b"],
            filename="hidden-b.pdf",
            file_hash="a1" * 32,
        )
        scoped_with_prices = AccessScope(
            principal_type="user",
            principal_id="1",
            hotel_ids={seeded["hotel_a"].id},
            can_view_prices=True,
        )
        scoped_without_prices = AccessScope(
            principal_type="user",
            principal_id="2",
            hotel_ids={seeded["hotel_a"].id},
            can_view_prices=False,
        )

        total = internal.aggregate_business(
            db,
            entity="budget",
            kind="total",
            query="total presupuestos",
            access_scope=scoped_with_prices,
        )
        redacted = internal.aggregate_business(
            db,
            entity="budget",
            kind="total",
            query="total presupuestos de mas de 1000",
            access_scope=scoped_without_prices,
        )

    assert total["rows"] == [
        {
            "metric": "total_amount",
            "value": 9999.0,
            "label": "suma de importes de presupuestos",
            "count": 1,
        }
    ]
    assert redacted["rows"] == []
    assert redacted["price_redacted"] is True
    assert "amount_min" not in redacted["filters"]


def test_resolved_document_payload_hides_structured_prices_without_permission():
    from app.services.business_redaction import redact_business_payload_for_scope

    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        budget = _add_budget(
            db,
            budget_number="2026/STRUCTURED",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="structured.pdf",
            file_hash="b1" * 32,
        )
        details = internal.get_document_full_details(db, budget.document_id)
        scope = AccessScope(principal_type="user", principal_id="3", can_view_prices=False)

    redacted = redact_business_payload_for_scope(
        {"document": details, "related": [{"entities": details["entities"]}]},
        scope,
    )

    budget_payload = redacted["document"]["entities"]["budget"]
    related_budget_payload = redacted["related"][0]["entities"]["budget"]
    assert budget_payload["total_amount"] is None
    assert budget_payload["currency"] is None
    assert budget_payload["lines_preview"][0]["unit_price"] is None
    assert budget_payload["lines_preview"][0]["total_price"] is None
    assert related_budget_payload["total_amount"] is None
    assert "9999" not in str(redacted)


def test_reconciliation_is_scoped_and_redacts_amounts_without_price_permission():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        user = User(
            email="gestor-recon@local",
            name="Gestor Recon",
            password_hash=hash_password("secret"),
            role="gestor",
            is_active=True,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Gestor Recon Hotel A sin precios",
            permissions_json={
                "hotel_ids": [seeded["hotel_a"].id],
                "allow_all_hotels": False,
                "can_view_prices": False,
                "can_search_budgets": True,
            },
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))
        visible = _add_budget(
            db,
            budget_number="2026/RECON-A",
            hotel=seeded["hotel_a"],
            chain=seeded["chain_a"],
            filename="recon-a.pdf",
            file_hash="c1" * 32,
        )
        hidden = _add_budget(
            db,
            budget_number="2026/RECON-B",
            hotel=seeded["hotel_b"],
            chain=seeded["chain_b"],
            filename="recon-b.pdf",
            file_hash="d1" * 32,
        )
        hidden_issue = ReconciliationIssue(
            kind="accepted_budget_without_order",
            severity="warning",
            status="pending",
            title="Hidden",
            description="Hidden issue",
            budget_id=hidden.id,
            document_id=hidden.document_id,
            expected_amount=9999.0,
        )
        db.add(hidden_issue)
        db.commit()
        token = create_access_token(str(user.id))

    generated = client.post("/reconciliation/issues/generate", headers={"Authorization": f"Bearer {token}"})
    listed = client.get("/reconciliation/issues", headers={"Authorization": f"Bearer {token}"})
    hidden_update = client.patch(
        f"/reconciliation/issues/{hidden_issue.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "reviewed"},
    )

    assert generated.status_code == 200
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert any(item["document_id"] == visible.document_id for item in listed_payload)
    assert all(item["document_id"] != hidden.document_id for item in listed_payload)
    assert all(item["expected_amount"] is None and item["actual_amount"] is None for item in listed_payload)
    assert "9999" not in str(listed_payload)
    assert hidden_update.status_code == 404


def test_invoice_creation_rejects_document_outside_user_scope():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        user = User(
            email="gestor-invoices@local",
            name="Gestor Facturas",
            password_hash=hash_password("secret"),
            role="gestor",
            is_active=True,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Gestor Facturas Hotel A",
            permissions_json={
                "hotel_ids": [seeded["hotel_a"].id],
                "allow_all_hotels": False,
                "can_view_prices": True,
                "can_search_budgets": True,
            },
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))
        hidden_budget = _add_budget(
            db,
            budget_number="2026/INVOICE-HIDDEN",
            hotel=seeded["hotel_b"],
            chain=seeded["chain_b"],
            filename="invoice-hidden.pdf",
            file_hash="e1" * 32,
        )
        token = create_access_token(str(user.id))

    response = client.post(
        "/invoices",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_id": hidden_budget.document_id,
            "invoice_number": "F-HIDDEN",
            "supplier_name": "Proveedor",
            "total_amount": 100,
        },
    )

    assert response.status_code == 404


def test_thumbnail_endpoint_respects_user_hotel_scope(tmp_path, monkeypatch):
    import app.services.thumbnail as thumbnail_service

    client, sessions = _test_client()
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    monkeypatch.setattr(thumbnail_service, "THUMBNAIL_DIR", tmp_path / "thumbnails")

    file_hash = "6" * 64
    stored_dir = tmp_path / file_hash[:2]
    stored_dir.mkdir(parents=True)
    Image.new("RGB", (20, 20), color="white").save(stored_dir / f"{file_hash}.png")

    with sessions() as db:
        seeded = _seed_base(db)
        user = User(
            email="gestor@local",
            name="Gestor",
            password_hash=hash_password("secret"),
            role="gestor",
            is_active=True,
        )
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Gestor Hotel A",
            permissions_json={
                "chain_ids": [],
                "hotel_ids": [seeded["hotel_a"].id],
                "allow_all_hotels": False,
                "denied_tags": [],
                "can_view_prices": False,
                "can_search_budgets": False,
            },
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))
        document = Document(
            original_filename="hotel-b.png",
            stored_filename=f"{file_hash[:2]}/{file_hash}.png",
            source_path="/data/input/imagenes/hotel-b.png",
            file_hash=file_hash,
            mime_type="image/png",
            extension=".png",
            file_size=100,
            document_type="imagen",
            status="processed",
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentAccessMetadata(
                document_id=document.id,
                chain_id=seeded["chain_b"].id,
                hotel_id=seeded["hotel_b"].id,
                assignment_status="assigned",
                assignment_source="manual",
                tags_json=[],
            )
        )
        db.commit()
        token = create_access_token(str(user.id))
        document_id = document.id

    response = client.get(f"/documents/{document_id}/thumbnail", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404

    preview_response = client.get(
        f"/documents/{document_id}/preview", headers={"Authorization": f"Bearer {token}"}
    )

    assert preview_response.status_code == 404


def test_specific_folder_rule_wins_and_equal_conflict_quarantines():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        document = Document(
            original_filename="obra.pdf",
            stored_filename="33/obra.pdf",
            source_path=r"C:\data\input\presupuestos\cadena-a\hotel-a\obra.pdf",
            file_hash="3" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=500,
            document_type="presupuesto",
            status="processed",
        )
        db.add(document)
        db.flush()
        db.add(
            FolderAssignmentRule(
                name="Cadena A general",
                pattern="/presupuestos/cadena-a/",
                match_type="contains",
                chain_id=seeded["chain_a"].id,
                hotel_id=None,
                tags_json=["cadena"],
            )
        )
        db.add(
            FolderAssignmentRule(
                name="Hotel A especifica",
                pattern="/presupuestos/cadena-a/hotel-a/",
                match_type="contains",
                chain_id=seeded["chain_a"].id,
                hotel_id=seeded["hotel_a"].id,
                tags_json=["obra"],
            )
        )
        apply_folder_rules_to_document(db, document)
        metadata = db.scalar(select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id == document.id))

        assert metadata.assignment_status == "assigned"
        assert metadata.hotel_id == seeded["hotel_a"].id
        assert metadata.tags_json == ["obra"]

        conflict_doc = Document(
            original_filename="conflicto.pdf",
            stored_filename="44/conflicto.pdf",
            source_path="/data/input/conflicto/conflicto.pdf",
            file_hash="4" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=500,
            document_type="desconocido",
            status="processed",
        )
        db.add(conflict_doc)
        db.flush()
        db.add(
            FolderAssignmentRule(
                name="Conflicto A",
                pattern="/data/input/conflicto/",
                match_type="contains",
                chain_id=seeded["chain_a"].id,
                hotel_id=seeded["hotel_a"].id,
                tags_json=[],
            )
        )
        db.add(
            FolderAssignmentRule(
                name="Conflicto B",
                pattern="/data/input/conflicto/",
                match_type="contains",
                chain_id=seeded["chain_b"].id,
                hotel_id=seeded["hotel_b"].id,
                tags_json=[],
            )
        )
        db.flush()
        apply_folder_rules_to_document(db, conflict_doc)
        conflict_metadata = db.scalar(
            select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id == conflict_doc.id)
        )

        assert conflict_metadata.assignment_status == "quarantine"
        assert conflict_metadata.assignment_source == "conflict"


# ---------------------------------------------------------------------------
# DATA-03: pagination / totals for scoped users must come from the
# SQL filter, not from a 500-row candidate cap. These tests seed
# enough documents to overflow the old candidate window and then
# check that the user still sees the right page on every offset.
# ---------------------------------------------------------------------------


def _add_scoped_document(
    db: Session,
    *,
    filename: str,
    chain: HotelChain,
    hotel: Hotel,
    file_hash_seed: int,
    document_type: str = "presupuesto",
    status: str = "processed",
    assignment_status: str = "assigned",
) -> Document:
    document = Document(
        original_filename=filename,
        stored_filename=f"{file_hash_seed:02d}/{filename}",
        source_path=f"/data/input/{chain.name}/{hotel.name}/{filename}",
        file_hash=str(file_hash_seed) * 64,
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1000,
        document_type=document_type,
        status=status,
        confidence=0.9,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentAccessMetadata(
            document_id=document.id,
            chain_id=chain.id,
            hotel_id=hotel.id,
            assignment_status=assignment_status,
            assignment_source="manual",
            tags_json=[],
        )
    )
    return document


def _scoped_user(db: Session, *, email: str, hotel_ids: list[int]) -> User:
    user = User(
        email=email,
        name=email.split("@")[0].title(),
        password_hash=hash_password("secret"),
        role="operario",
        is_active=True,
    )
    db.add(user)
    db.flush()
    group = AccessGroup(
        name=f"Group for {email}",
        permissions_json={
            "chain_ids": [],
            "hotel_ids": hotel_ids,
            "allow_all_hotels": False,
            "denied_tags": [],
            "can_view_prices": False,
            "can_search_budgets": False,
        },
    )
    db.add(group)
    db.flush()
    db.add(
        AccessGroupMember(
            group_id=group.id,
            principal_type="user",
            principal_id=str(user.id),
        )
    )
    return user


def test_documents_pagination_is_correct_for_scoped_user_above_500_rows():
    """The old candidate cap (max(limit+offset, 500)) made pages 2+
    return wrong rows when many hidden documents preceded the visible
    ones. With the SQL-side predicate the visible set is correct
    regardless of how many hidden rows exist before the user's
    window.
    """
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        # 600 documents assigned to hotel_b (out of scope) so they
        # sort before the hotel_a ones in the listing and overflow
        # the old 500-row cap.
        for i in range(600):
            _add_scoped_document(
                db,
                filename=f"out_{i:04d}.pdf",
                chain=seeded["chain_b"],
                hotel=seeded["hotel_b"],
                file_hash_seed=(i % 9) + 1,
            )
        # 3 documents assigned to hotel_a (in scope).
        in_scope_ids = set()
        for i in range(3):
            doc = _add_scoped_document(
                db,
                filename=f"in_{i}.pdf",
                chain=seeded["chain_a"],
                hotel=seeded["hotel_a"],
                file_hash_seed=(i % 9) + 1,
            )
            in_scope_ids.add(doc.original_filename)
        scoped_user = _scoped_user(db, email="op@local", hotel_ids=[seeded["hotel_a"].id])
        db.commit()
        token = create_access_token(str(scoped_user.id))

    # Page 1: only the 3 in-scope documents, all 3 returned.
    page_1 = client.get(
        "/documents?limit=10&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page_1.status_code == 200
    page_1_filenames = {item["original_filename"] for item in page_1.json()}
    assert page_1_filenames == in_scope_ids

    # Page 2 (offset = limit): must be empty, not filled with
    # out-of-scope documents. This is exactly the bug the audit
    # flagged as DATA-03.
    page_2 = client.get(
        "/documents?limit=10&offset=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page_2.status_code == 200
    assert page_2.json() == []


def test_budgets_pagination_is_correct_for_scoped_user_above_200_rows():
    client, sessions = _test_client()
    with sessions() as db:
        seeded = _seed_base(db)
        # 250 out-of-scope budgets (overflows the old 200 cap).
        for i in range(250):
            _add_budget(
                db,
                budget_number=f"OUT-{i:04d}",
                hotel=seeded["hotel_b"],
                chain=seeded["chain_b"],
                filename=f"out_b_{i:04d}.pdf",
                file_hash=str((i % 9) + 1) * 64,
            )
        # 4 in-scope budgets.
        for i in range(4):
            _add_budget(
                db,
                budget_number=f"IN-{i:04d}",
                hotel=seeded["hotel_a"],
                chain=seeded["chain_a"],
                filename=f"in_b_{i:04d}.pdf",
                file_hash=str((i % 9) + 1) * 64,
            )
        scoped_user = _scoped_user(db, email="b@local", hotel_ids=[seeded["hotel_a"].id])
        db.commit()
        token = create_access_token(str(scoped_user.id))

    response = client.get(
        "/budgets?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    items = response.json()
    # All returned budgets must reference in-scope numbers only.
    numbers = {item["budget_number"] for item in items}
    assert numbers, "scoped user should still see their budgets"
    assert all(number.startswith("IN-") for number in numbers)
    assert len(numbers) == 4


def test_apply_access_predicates_returns_no_rows_for_empty_scope():
    """An empty scope (deny-by-default with no groups) must produce
    zero rows from the listing endpoints, not a 500-row capped
    sample that leaks documents.
    """
    from app.services.tenant_access import (
        apply_access_predicates,
        resolve_user_access_scope,
    )
    from app.models import Document

    sessions = _session_factory_for_predicates_test()
    with sessions() as db:
        seeded = _seed_base(db)
        # A document the user would otherwise see.
        _add_scoped_document(
            db,
            filename="in_scope_doc.pdf",
            chain=seeded["chain_a"],
            hotel=seeded["hotel_a"],
            file_hash_seed=1,
        )
        db.commit()

        user = User(
            email="noperms@local",
            name="NoPerms",
            password_hash=hash_password("secret"),
            role="operario",
            is_active=True,
        )
        db.add(user)
        db.commit()

        scope = resolve_user_access_scope(db, user)
        assert scope.is_admin is False
        assert not scope.allow_all_hotels
        assert not scope.hotel_ids

        stmt = select(Document).where(Document.deleted_at.is_(None))
        filtered_stmt = apply_access_predicates(stmt, scope)
        rows = list(db.scalars(filtered_stmt).all())
        assert rows == [], f"empty scope should see zero rows, got {len(rows)}"


def _session_factory_for_predicates_test() -> sessionmaker[Session]:
    """In-memory SQLite engine, used to verify the SQL predicate
    shape without the overhead of the FastAPI test client.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
