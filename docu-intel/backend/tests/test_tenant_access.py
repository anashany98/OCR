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
    IntegrationClient,
    User,
)
from app.services.access_policy import ensure_default_access_policies
from app.services.integration_security import hash_integration_api_key
from app.services.tenant_access import apply_folder_rules_to_document


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
