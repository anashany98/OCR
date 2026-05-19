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
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    AccessPolicy,
    AccessGroup,
    AccessGroupMember,
    AuditLog,
    Budget,
    BudgetLine,
    Document,
    DocumentAccessMetadata,
    DocumentPage,
    ExtractionJob,
    Hotel,
    HotelChain,
    IntegrationClient,
    TechnicianAccessProfile,
)
from app.services.access_policy import ensure_default_access_policies
from app.services.integration_security import hash_integration_api_key
from app.services.redaction import redact_sensitive_text


def _test_client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
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


def _seed_integration_data(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as db:
        ensure_default_access_policies(db)
        db.add(
            IntegrationClient(
                name="external-tool",
                api_key_hash=hash_integration_api_key("secret-key"),
                scopes_json=["read", "upload"],
                is_active=True,
            )
        )
        chain = HotelChain(name="Cadena Demo", is_active=True)
        db.add(chain)
        db.flush()
        hotel = Hotel(chain_id=chain.id, name="Hotel Demo", code="DEMO", is_active=True)
        db.add(hotel)
        db.flush()
        group = AccessGroup(
            name="Tecnicos demo",
            permissions_json={
                "chain_ids": [],
                "hotel_ids": [hotel.id],
                "allow_all_hotels": False,
                "denied_tags": [],
                "can_view_prices": False,
                "can_search_budgets": False,
            },
        )
        db.add(group)
        db.flush()
        db.add_all(
            [
                AccessGroupMember(group_id=group.id, principal_type="technician", principal_id="tecnico-17"),
                AccessGroupMember(group_id=group.id, principal_type="technician", principal_id="jefe-1"),
            ]
        )
        document = Document(
            original_filename="presupuesto_2026_143.pdf",
            stored_filename="aa/presupuesto.pdf",
            source_path="/data/input/presupuestos/presupuesto_2026_143.pdf",
            file_hash="a" * 64,
            mime_type="application/pdf",
            extension=".pdf",
            file_size=1200,
            document_type="presupuesto",
            status="processed",
            confidence=0.86,
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
                tags_json=[],
            )
        )
        db.add(
            DocumentPage(
                document_id=document.id,
                page_number=1,
                text="Presupuesto 2026/143 Cliente X Total 1.245,60 € Referencia ABC123 precio unitario 22,50 €",
                ocr_confidence=0.86,
            )
        )
        budget = Budget(
            document_id=document.id,
            budget_number="2026/143",
            client_name="Cliente X",
            date=date(2026, 5, 14),
            total_amount=1245.60,
            currency="EUR",
            status="aceptado",
            accepted_detected=True,
            confidence=0.86,
        )
        db.add(budget)
        db.flush()
        db.add(
            BudgetLine(
                budget_id=budget.id,
                reference="ABC123",
                description="Elemento detectado",
                quantity=2,
                unit="ud",
                unit_price=22.50,
                total_price=45.00,
                confidence=0.88,
            )
        )
        db.commit()


def _headers(technician_id: str = "tecnico-17", api_key: str = "secret-key") -> dict[str, str]:
    return {"X-DocuIntel-API-Key": api_key, "X-Technician-Id": technician_id}


def test_integration_auth_requires_api_key_and_technician_id(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)

    missing_key = client.get("/integrations/v1/manifest", headers={"X-Technician-Id": "tecnico-17"})
    missing_technician = client.get("/integrations/v1/manifest", headers={"X-DocuIntel-API-Key": "secret-key"})
    bad_key = client.get("/integrations/v1/manifest", headers=_headers(api_key="bad"))

    assert missing_key.status_code == 401
    assert missing_technician.status_code == 400
    assert bad_key.status_code == 401


def test_manifest_exposes_safe_tool_guidance(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)

    response = client.get("/integrations/v1/manifest", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert "get_budget_by_number" in {tool["name"] for tool in payload["tools"]}
    assert any("No pedir SQL" in rule for rule in payload["rules"])
    assert any("No mezclar presupuestos" in rule for rule in payload["rules"])


def test_budget_tool_redacts_prices_for_default_policy_and_uses_exact_lookup(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/143"}},
    )
    near_match = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/14"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["budget_number"] == "2026/143"
    assert "total_amount" not in payload["data"]
    assert "currency" not in payload["data"]
    assert "unit_price" not in payload["data"]["lines"][0]
    assert "total_price" not in payload["data"]["lines"][0]
    assert "1.245,60" not in str(payload)
    assert "22,50" not in str(payload)
    assert "[IMPORTE OCULTO]" in payload["sources"][0]["excerpt"]
    assert "budget.total_amount" in payload["redactions"]
    assert near_match.status_code == 200
    assert near_match.json()["data"]["status"] == "not_found"
    assert near_match.json()["sources"] == []


def test_authorized_policy_can_receive_budget_prices(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)
    with sessions() as db:
        policy = db.scalar(select(AccessPolicy).where(AccessPolicy.name == "precios_autorizados"))
        db.add(TechnicianAccessProfile(technician_id="jefe-1", technician_name="Jefe", access_policy_id=policy.id))
        db.commit()

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(technician_id="jefe-1"),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/143"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["total_amount"] == 1245.60
    assert payload["data"]["currency"] == "EUR"
    assert payload["data"]["lines"][0]["unit_price"] == 22.50
    assert payload["redactions"] == []


def test_integration_audit_records_policy_tool_and_redactions(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/143"}},
    )

    assert response.status_code == 200
    with sessions() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "integration_tool_execute"))
        assert audit is not None
        assert audit.details_json["integration_client"] == "external-tool"
        assert audit.details_json["technician_id"] == "tecnico-17"
        assert audit.details_json["policy"] == "operario_minimo"
        assert audit.details_json["tool"] == "get_budget_by_number"
        assert "budget.total_amount" in audit.details_json["redactions"]


def test_integration_tool_sandbox_adds_warning_and_audit_action(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "get_budget_by_number", "arguments": {"budget_number": "2026/143"}, "sandbox": True},
    )

    assert response.status_code == 200
    assert any("Sandbox activo" in warning for warning in response.json()["warnings"])
    with sessions() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "integration_tool_sandbox")) is not None


def test_search_budgets_is_forbidden_for_default_minimum_policy(tmp_path):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)

    response = client.post(
        "/integrations/v1/tools/execute",
        headers=_headers(),
        json={"tool": "search_budgets", "arguments": {"query": "2026"}},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Tool not allowed by access policy"


def test_upload_requires_upload_scope(tmp_path, monkeypatch):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)
    with sessions() as db:
        read_only = IntegrationClient(
            name="read-only",
            api_key_hash=hash_integration_api_key("read-only-key"),
            scopes_json=["read"],
            is_active=True,
        )
        db.add(read_only)
        db.commit()

    response = client.post(
        "/integrations/v1/documents/upload",
        headers=_headers(api_key="read-only-key"),
        files={"file": ("nota.txt", b"Presupuesto 2026/143", "text/plain")},
    )

    assert response.status_code == 403


def test_upload_with_scope_registers_document_and_job(tmp_path, monkeypatch):
    client, sessions = _test_client(tmp_path)
    _seed_integration_data(sessions)
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "integration_enqueue_uploads", False)

    response = client.post(
        "/integrations/v1/documents/upload",
        headers=_headers(),
        files={"file": ("nota.txt", b"Referencia ABC123", "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["original_filename"] == "nota.txt"
    assert payload["job"]["status"] == "pending"
    with sessions() as db:
        assert db.scalar(select(ExtractionJob).where(ExtractionJob.id == payload["job"]["id"])) is not None


def test_redacts_money_amounts_in_ocr_excerpts():
    text = "Total 1.245,60 €; precio unitario 22,50 €; margen 18%; cantidad 2 ud"

    redacted = redact_sensitive_text(text)

    assert "1.245,60" not in redacted
    assert "22,50" not in redacted
    assert "18%" not in redacted
    assert "€" not in redacted
    assert "[IMPORTE OCULTO]" in redacted
    assert "cantidad 2 ud" in redacted
