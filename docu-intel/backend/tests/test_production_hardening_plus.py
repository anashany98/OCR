from __future__ import annotations

import os
from datetime import date
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    DocumentPage,
    Order,
    Plan,
    SensitiveTag,
    User,
)
from app.services.access_policy import ensure_default_access_policies

settings.database_url = "sqlite+pysqlite:///:memory:"


def _test_client(tmp_path: Path | None = None) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    if tmp_path:
        settings.files_dir = tmp_path / "files"
        settings.input_dir = tmp_path / "input"
        settings.files_dir.mkdir(parents=True, exist_ok=True)
        settings.input_dir.mkdir(parents=True, exist_ok=True)

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


def _user(db: Session, *, role: str = "admin", email: str | None = None) -> tuple[str, User]:
    ensure_default_access_policies(db)
    user = User(
        email=email or f"{role}@local",
        name=role.title(),
        password_hash=hash_password("secret"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    token = create_access_token(str(user.id))
    db.commit()
    return token, user


def _document(
    db: Session,
    filename: str,
    *,
    document_type: str = "presupuesto",
    status: str = "processed",
    text: str = "Presupuesto 2026/143 referencia ABC123",
    confidence: float = 0.9,
    tags: list[str] | None = None,
    stored_filename: str | None = None,
) -> Document:
    document = Document(
        original_filename=filename,
        stored_filename=stored_filename or f"aa/{filename}",
        source_path=f"/data/input/{document_type}/{filename}",
        file_hash=("1" * 63) + str(len(filename) % 10),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1000,
        document_type=document_type,
        status=status,
        quality_status="processed_ok",
        quality_score=0.95,
        quality_flags_json=[],
        confidence=confidence,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(DocumentPage(document_id=document.id, page_number=1, text=text, ocr_confidence=confidence))
    db.add(
        DocumentAccessMetadata(
            document_id=document.id,
            assignment_status="quarantine",
            assignment_source="test",
            tags_json=tags or [],
        )
    )
    db.flush()
    return document


def test_effective_access_shows_role_type_tags_and_redaction_policy():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token, _ = _user(db, role="admin")
        _, gestor = _user(db, role="gestor", email="gestor-plus@local")
        group = AccessGroup(
            name="Gestor operativo sin contabilidad",
            permissions_json={
                "allow_all_hotels": True,
                "allow_unassigned_documents": True,
                "can_view_prices": False,
                "can_search_budgets": True,
                "allowed_document_types": ["presupuesto", "pedido"],
                "denied_tags": ["contabilidad"],
            },
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(gestor.id)))
        db.commit()

    response = client.get(
        f"/admin/access/effective?principal_type=user&principal_id={gestor.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["principal_type"] == "user"
    assert payload["can_view_prices"] is False
    assert payload["can_search_budgets"] is True
    assert payload["allowed_document_types"] == ["pedido", "presupuesto"]
    assert payload["denied_tags"] == ["contabilidad"]
    assert "budget.total_amount" in payload["redacted_fields"]


def test_bulk_tags_then_document_list_respects_internal_permission_scope():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token, _ = _user(db, role="admin")
        gestor_token, gestor = _user(db, role="gestor", email="gestor-tags@local")
        public_doc = _document(db, "publico.pdf", document_type="presupuesto")
        blocked_doc = _document(db, "contabilidad.pdf", document_type="factura")
        group = AccessGroup(
            name="Gestor sin contabilidad",
            permissions_json={"allow_all_hotels": True, "allow_unassigned_documents": True, "denied_tags": ["contabilidad"]},
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(gestor.id)))
        db.commit()

    tagged = client.post(
        "/admin/documents/bulk-tags",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"document_ids": [blocked_doc.id], "add_tags": ["contabilidad"], "remove_tags": []},
    )
    docs = client.get("/documents", headers={"Authorization": f"Bearer {gestor_token}"})

    assert tagged.status_code == 200
    assert tagged.json()["updated"] == 1
    assert docs.status_code == 200
    visible_ids = {item["id"] for item in docs.json()}
    assert public_doc.id in visible_ids
    assert blocked_doc.id not in visible_ids


def test_quality_summary_and_recalculate_detect_missing_business_fields():
    client, sessions = _test_client()
    with sessions() as db:
        token, _ = _user(db, role="admin")
        low = _document(db, "ocr-bajo.pdf", text="x", confidence=0.42)
        missing_budget = _document(db, "presupuesto-sin-numero.pdf", document_type="presupuesto", text="Presupuesto sin numero")
        missing_order = _document(db, "pedido-sin-proveedor.pdf", document_type="pedido", text="Pedido 2026/22")
        missing_invoice = _document(db, "factura-sin-fecha.pdf", document_type="factura", text="Factura F-1 total 99 euros")
        plan_doc = _document(db, "plano.pdf", document_type="plano", text="Plano sin escala")
        db.add(Order(document_id=missing_order.id, order_number="P-1", supplier_name=None, date=date(2026, 5, 17)))
        db.add(Budget(document_id=missing_budget.id, budget_number=None, client_name="Cliente", date=date(2026, 5, 17)))
        db.add(Plan(document_id=plan_doc.id, project_name="Obra", has_valid_scale=False))
        low.quality_status = "processed_ok"
        db.commit()

    recalc = client.post("/admin/quality/recalculate", headers={"Authorization": f"Bearer {token}"}, json={"limit": 100})
    summary = client.get("/admin/quality/summary", headers={"Authorization": f"Bearer {token}"})

    assert recalc.status_code == 200
    assert recalc.json()["updated"] >= 5
    assert summary.status_code == 200
    rules = summary.json()["rules"]
    assert rules["ocr_low"]["count"] >= 1
    assert rules["missing_budget_number"]["count"] >= 1
    assert rules["missing_order_supplier"]["count"] >= 1
    assert rules["missing_invoice_date"]["count"] >= 1
    assert rules["plan_without_scale"]["count"] >= 1


def test_production_readiness_and_file_integrity_report_operational_checks(tmp_path: Path):
    client, sessions = _test_client(tmp_path)
    with sessions() as db:
        token, _ = _user(db, role="admin")
        stored = "aa/missing.pdf"
        _document(db, "missing.pdf", stored_filename=stored)
        orphan_dir = settings.files_dir / "zz"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        (orphan_dir / "orphan.pdf").write_bytes(b"orphan")
        db.commit()

    readiness = client.get("/admin/production/readiness", headers={"Authorization": f"Bearer {token}"})
    integrity = client.get("/admin/storage/integrity?limit=100", headers={"Authorization": f"Bearer {token}"})

    assert readiness.status_code == 200
    check_keys = {item["key"] for item in readiness.json()["checks"]}
    assert {"database", "redis", "workers", "watcher", "files_dir", "input_dir", "backups", "integration_manifest"} <= check_keys
    assert integrity.status_code == 200
    assert integrity.json()["missing_files"] == 1
    assert integrity.json()["orphan_files"] == 1


def test_paginated_operations_documents_returns_total_and_ordered_items():
    client, sessions = _test_client()
    with sessions() as db:
        token, _ = _user(db, role="admin")
        first = _document(db, "a.pdf")
        second = _document(db, "b.pdf")
        third = _document(db, "c.pdf")
        db.commit()

    response = client.get(
        "/admin/operations/documents?limit=2&offset=1&status=processed",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert len(payload["items"]) == 2
    assert {item["id"] for item in payload["items"]} <= {first.id, second.id, third.id}


def test_quality_rule_configuration_lists_threshold_and_sensitive_tags():
    client, sessions = _test_client()
    with sessions() as db:
        token, _ = _user(db, role="admin")
        db.add(SensitiveTag(name="contabilidad", description="Bloquea documentos contables", is_active=True))
        db.commit()

    response = client.get("/admin/quality/rules", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    # The endpoint must expose the configured operational threshold.
    assert payload["low_ocr_threshold"] == settings.low_ocr_confidence_threshold
    assert "contabilidad" in payload["sensitive_tags"]
    assert "missing_budget_number" in payload["business_rules"]
