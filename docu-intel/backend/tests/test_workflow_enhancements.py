from __future__ import annotations

import os
from datetime import date

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
    AccessGroup,
    AccessGroupMember,
    AuditLog,
    Budget,
    BudgetLine,
    Document,
    DocumentBlock,
    DocumentEntity,
    DocumentPage,
    ExtractionJob,
    Hotel,
    HotelChain,
    IntegrationClient,
    Order,
    Plan,
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

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def _admin_token(db: Session) -> str:
    ensure_default_access_policies(db)
    user = User(email="admin@local", name="Admin", password_hash=hash_password("secret"), role="admin", is_active=True)
    db.add(user)
    db.flush()
    token = create_access_token(str(user.id))
    db.commit()
    return token


def _gestor_token(db: Session) -> tuple[str, User]:
    user = User(email="gestor@local", name="Gestor", password_hash=hash_password("secret"), role="gestor", is_active=True)
    db.add(user)
    db.flush()
    token = create_access_token(str(user.id))
    db.commit()
    return token, user


def _document(db: Session, filename: str, *, document_type: str = "presupuesto", status: str = "processed") -> Document:
    chain = HotelChain(name=f"Cadena {filename}", is_active=True)
    db.add(chain)
    db.flush()
    hotel = Hotel(chain_id=chain.id, name=f"Hotel {filename}", code=None, is_active=True)
    db.add(hotel)
    db.flush()
    document = Document(
        original_filename=filename,
        stored_filename=f"aa/{filename}",
        source_path=f"/data/input/{document_type}/{filename}",
        file_hash=("9" * 63) + str(len(filename) % 10),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1000,
        document_type=document_type,
        status=status,
        quality_status="processed_ok",
        quality_score=0.9,
        quality_flags_json=[],
        confidence=0.9,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(DocumentPage(document_id=document.id, page_number=1, text=f"Documento {filename} referencia ABC123", ocr_confidence=0.9))
    db.flush()
    return document


def test_work_inbox_collects_ocr_unknown_duplicate_failed_and_business_items():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        low_ocr = _document(db, "ocr-bajo.pdf")
        low_page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == low_ocr.id))
        low_page.ocr_confidence = 0.42
        unknown = _document(db, "sin-clasificar.pdf", document_type="desconocido")
        duplicate = _document(db, "duplicado.pdf", status="duplicate")
        failed = _document(db, "fallido.pdf", status="failed")
        db.add(ExtractionJob(document_id=failed.id, job_type="extract", status="failed", error_message="OCR error"))
        missing = _document(db, "sin-campos.pdf")
        missing.quality_status = "processed_missing_fields"
        budget = Budget(
            document_id=missing.id,
            budget_number="2026/NO-ORDER",
            client_name="Cliente",
            date=date(2026, 5, 16),
            status="aceptado",
            accepted_detected=True,
            confidence=0.8,
        )
        db.add(budget)
        db.commit()

    response = client.get("/admin/work-inbox", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    kinds = {item["kind"] for item in response.json()}
    assert {"low_ocr", "unknown_type", "duplicate", "failed_job", "missing_fields", "accepted_budget_without_order"} <= kinds


def test_work_inbox_bulk_actions_retry_failed_jobs_and_approve_high_ocr_pages():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        failed = _document(db, "fallido.pdf", status="failed")
        high_ocr = _document(db, "ocr-alto.pdf")
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == high_ocr.id))
        page.ocr_confidence = 0.92
        page.review_status = "pending"
        db.add(ExtractionJob(document_id=failed.id, job_type="extract", status="failed", error_message="boom"))
        db.commit()

    retry = client.post(
        "/admin/work-inbox/actions",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "retry_failed_jobs", "limit": 10},
    )
    approve = client.post(
        "/admin/work-inbox/actions",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "approve_high_confidence_ocr", "min_confidence": 0.85, "limit": 10},
    )

    assert retry.status_code == 200
    assert retry.json()["enqueued"] == 1
    assert approve.status_code == 200
    assert approve.json()["updated"] == 1
    with sessions() as db:
        assert db.scalar(select(DocumentPage).where(DocumentPage.ocr_confidence == 0.92)).review_status == "approved"


def test_production_checklist_reports_operational_items():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)

    response = client.get("/admin/production/checklist", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    keys = {item["key"] for item in response.json()["items"]}
    assert {"database", "redis", "watcher", "disk", "backup_runbook", "integration_manifest"} <= keys


def test_rule_preview_evaluates_pattern_without_saving_rule():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)

    response = client.post(
        "/admin/rules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={"path": r"C:\data\input\contabilidad\factura.pdf", "pattern": "/contabilidad/", "match_type": "contains", "tags_json": ["contabilidad"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"] is True
    assert payload["tags_json"] == ["contabilidad"]


def test_admin_integration_sandbox_executes_tool_with_redactions():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        client_model = IntegrationClient(
            name="external-tool",
            api_key_hash=hash_integration_api_key("secret-key"),
            scopes_json=["read"],
            is_active=True,
        )
        db.add(client_model)
        document = _document(db, "presupuesto.pdf")
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id))
        page.text = "Presupuesto 2026/143 Total 1.245,60 €"
        budget = Budget(
            document_id=document.id,
            budget_number="2026/143",
            client_name="Cliente",
            date=date(2026, 5, 16),
            total_amount=1245.60,
            currency="EUR",
            status="aceptado",
            accepted_detected=True,
            confidence=0.9,
        )
        db.add(budget)
        db.flush()
        db.add(BudgetLine(budget_id=budget.id, reference="ABC123", description="Linea", quantity=1, unit="ud", unit_price=10, total_price=10))
        db.commit()
        client_id = client_model.id

    response = client.post(
        "/admin/integration-sandbox/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={"client_id": client_id, "technician_id": "tech-1", "tool": "get_budget_by_number", "arguments": {"budget_number": "2026/143"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "get_budget_by_number"
    assert "total_amount" not in payload["data"]
    assert "[IMPORTE OCULTO]" in payload["sources"][0]["excerpt"]
    assert any("Sandbox" in warning for warning in payload["warnings"])


def test_redaction_preview_shows_what_principal_can_see():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        _, gestor = _gestor_token(db)
        group = AccessGroup(
            name="Gestor sin precios",
            permissions_json={"allow_all_hotels": True, "can_view_prices": False, "denied_tags": ["precios"]},
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(gestor.id)))
        db.commit()

    response = client.post(
        "/admin/security/redaction-preview",
        headers={"Authorization": f"Bearer {token}"},
        json={"principal_type": "user", "principal_id": str(gestor.id), "text": "Total 99,00 € margen 20%"},
    )

    assert response.status_code == 200
    assert response.json()["can_view_prices"] is False
    assert "99,00" not in response.json()["redacted_text"]
    assert "20%" not in response.json()["redacted_text"]


def test_guided_search_finds_reference_and_budget_exactly():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db, "presupuesto.pdf")
        db.add(DocumentEntity(document_id=document.id, entity_type="reference", entity_value="ABC123", normalized_value="abc123", confidence=0.9))
        db.add(Budget(document_id=document.id, budget_number="2026/143", client_name="Cliente", date=date(2026, 5, 16), confidence=0.9))
        db.commit()

    reference = client.get("/search/guided?mode=reference&q=ABC123", headers={"Authorization": f"Bearer {token}"})
    budget = client.get("/search/guided?mode=budget&q=2026/143", headers={"Authorization": f"Bearer {token}"})

    assert reference.status_code == 200
    assert reference.json()[0]["source_type"] == "guided_reference"
    assert budget.status_code == 200
    assert budget.json()[0]["source_type"] == "guided_budget"
