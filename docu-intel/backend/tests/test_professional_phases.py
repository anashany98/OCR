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
from app.core.security import create_access_token, hash_password, verify_password
from app.database.base import Base
from app.database.session import get_db
from app.models import Budget, Document, DocumentPage, Order, Plan, User


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
    user = User(email="admin@local", name="Admin", password_hash=hash_password("secret"), role="admin", is_active=True)
    db.add(user)
    db.flush()
    token = create_access_token(str(user.id))
    db.commit()
    return token


def _document(db: Session, filename: str = "doc.pdf", *, document_type: str = "presupuesto") -> Document:
    document = Document(
        original_filename=filename,
        stored_filename=f"aa/{filename}",
        source_path=f"/data/input/{document_type}/{filename}",
        file_hash=("a" * 63) + str(len(filename) % 10),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1200,
        document_type=document_type,
        status="processed",
        quality_status="processed_ok",
        quality_flags_json=[],
        confidence=0.9,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(DocumentPage(document_id=document.id, page_number=1, text="Texto original total 99,00", ocr_confidence=0.55))
    db.flush()
    return document


def test_work_items_are_persistent_and_commentable():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db)
        document_id = document.id
        db.commit()

    created = client.post(
        "/admin/work-items",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "missing_fields", "title": "Revisar campos", "description": "Falta total", "document_id": document_id, "priority": "high"},
    )
    assert created.status_code == 200
    work_item_id = created.json()["id"]

    comment = client.post(
        f"/admin/work-items/{work_item_id}/comments",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": "Lo reviso hoy"},
    )
    listed = client.get("/admin/work-items", headers={"Authorization": f"Bearer {token}"})

    assert comment.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["comments"][0]["body"] == "Lo reviso hoy"


def test_ocr_revision_updates_page_text_and_document_timeline_records_event():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db)
        page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id))
        document_id = document.id
        page_id = page.id
        db.commit()

    response = client.post(
        f"/documents/pages/{page_id}/ocr-revisions",
        headers={"Authorization": f"Bearer {token}"},
        json={"corrected_text": "Texto corregido total 99,00", "reason": "Corrección manual"},
    )
    timeline = client.get(f"/documents/{document_id}/timeline", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["original_text"] == "Texto original total 99,00"
    assert response.json()["corrected_text"] == "Texto corregido total 99,00"
    assert timeline.status_code == 200
    assert any(item["event_type"] == "ocr_revision" for item in timeline.json())


def test_reconciliation_detects_budget_without_order_and_allows_status_update():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db)
        db.add(
            Budget(
                document_id=document.id,
                budget_number="B-100",
                client_name="Cliente",
                date=date(2026, 5, 18),
                total_amount=100,
                status="aceptado",
                accepted_detected=True,
            )
        )
        db.commit()

    issues = client.post("/reconciliation/issues/generate", headers={"Authorization": f"Bearer {token}"})
    assert issues.status_code == 200
    issue = next(item for item in issues.json() if item["kind"] == "accepted_budget_without_order")

    updated = client.patch(
        f"/reconciliation/issues/{issue['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "reviewed", "resolution_notes": "Pedido externo confirmado"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "reviewed"


def test_invoice_endpoint_feeds_reconciliation():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db, "factura.pdf", document_type="factura")
        document_id = document.id
        db.commit()

    invoice = client.post(
        "/invoices",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": document_id, "invoice_number": "F-200", "supplier_name": "Proveedor", "total_amount": 200},
    )
    issues = client.post("/reconciliation/issues/generate", headers={"Authorization": f"Bearer {token}"})

    assert invoice.status_code == 200
    assert invoice.json()["invoice_number"] == "F-200"
    assert any(item["kind"] == "invoice_without_order" for item in issues.json())


def test_saved_searches_notification_rules_and_admin_users_are_available():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)

    saved_search = client.post(
        "/search/saved",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Facturas críticas", "query": "factura error", "mode": "hybrid", "filters_json": {"document_type": "factura"}},
    )
    rule = client.post(
        "/admin/notification-rules",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "OCR fallido", "event_type": "ocr_failed", "channel": "webhook", "target": "http://example.test/hook"},
    )
    user = client.post(
        "/admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "gestor@example.test", "name": "Gestor", "role": "gestor", "password": "super-secret-password"},
    )

    assert saved_search.status_code == 200
    assert rule.status_code == 200
    assert user.status_code == 200
    with sessions() as db:
        created_user = db.scalar(select(User).where(User.email == "gestor@example.test"))
        assert created_user is not None
        assert verify_password("super-secret-password", created_user.password_hash)


def test_plan_measurements_persist_manual_measurement_and_discrepancy_flag():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db, "plano.pdf", document_type="plano")
        plan = Plan(document_id=document.id, project_name="Demo", scale_text="1:50", scale_ratio=50, has_valid_scale=True)
        db.add(plan)
        db.commit()
        plan_id = plan.id

    response = client.post(
        f"/plans/{plan_id}/measurements",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "label": "Habitación 101",
            "page_number": 1,
            "measurement_type": "distance",
            "value_m": 3.2,
            "ocr_value_m": 2.6,
            "points_json": [{"x": 10, "y": 10}, {"x": 100, "y": 10}],
        },
    )

    assert response.status_code == 200
    assert response.json()["has_discrepancy"] is True
