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

from app.core.config import settings

settings.database_url = "sqlite+pysqlite:///:memory:"

from app.api.router import api_router
from app.core.security import create_access_token, hash_password
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    AccessGroup,
    AccessGroupMember,
    Budget,
    BudgetLine,
    Document,
    DocumentAccessMetadata,
    DocumentEntity,
    ExtractionJob,
    Hotel,
    HotelChain,
    Order,
    User,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _test_client() -> tuple[TestClient, sessionmaker[Session]]:
    sessions = _session_factory()
    app = FastAPI()
    app.include_router(api_router)

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), sessions


def _admin_token(db: Session) -> str:
    user = User(email="admin@local", name="Admin", password_hash=hash_password("secret"), role="admin", is_active=True)
    db.add(user)
    db.flush()
    return create_access_token(str(user.id))


def _document(db: Session, filename: str = "doc.pdf", *, status: str = "processed", tags: list[str] | None = None) -> Document:
    chain = HotelChain(name=f"Cadena {filename}", is_active=True)
    db.add(chain)
    db.flush()
    hotel = Hotel(chain_id=chain.id, name=f"Hotel {filename}", code=None, is_active=True)
    db.add(hotel)
    db.flush()
    document = Document(
        original_filename=filename,
        stored_filename=f"aa/{filename}",
        source_path=f"/data/input/presupuestos/{filename}",
        file_hash=("a" * 63) + str(len(filename) % 10),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1000,
        document_type="presupuesto",
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
            assignment_status="assigned",
            assignment_source="manual",
            tags_json=tags or [],
        )
    )
    return document


def test_ingestion_event_and_watched_file_are_recorded():
    from app.services.ingestion_events import record_ingestion_event, upsert_watched_file
    from app.models import IngestionEvent, WatchedFile

    sessions = _session_factory()
    with sessions() as db:
        watched = upsert_watched_file(
            db,
            path="/data/input/pedidos/a.pdf",
            status="detected",
            size_bytes=123,
            mtime_epoch=1000,
        )
        record_ingestion_event(db, event_type="detected", source_path=watched.path, watched_file=watched)
        db.commit()

        saved_watched = db.scalar(select(WatchedFile).where(WatchedFile.path == "/data/input/pedidos/a.pdf"))
        saved_event = db.scalar(select(IngestionEvent).where(IngestionEvent.source_path == "/data/input/pedidos/a.pdf"))

    assert saved_watched is not None
    assert saved_watched.status == "detected"
    assert saved_event is not None
    assert saved_event.event_type == "detected"


def test_admin_operations_status_reports_ingestion_and_queue_counts():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db)
        db.add(ExtractionJob(document_id=document.id, job_type="extract", status="pending"))
        db.commit()

    response = client.get("/admin/operations-status", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["jobs_by_status"]["pending"] == 1
    assert "disk" in payload
    assert "input_dir" in payload["disk"]


def test_admin_operations_overview_reports_quality_and_eta():
    from app.models import WatchedFile

    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db, status="needs_review")
        document.quality_status = "processed_low_quality"
        db.add(ExtractionJob(document_id=document.id, job_type="extract", status="pending"))
        db.add(WatchedFile(path="/data/input/presupuestos/doc.pdf", status="queued", document_id=document.id))
        db.commit()

    response = client.get("/admin/operations/overview", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["documents"]["by_quality_status"]["processed_low_quality"] == 1
    assert payload["jobs"]["pending_or_processing"] == 1
    assert payload["watcher"]["last_sources"][0]["source_path"].endswith("doc.pdf")


def test_file_security_blocks_renamed_executable(tmp_path):
    from app.services.file_security import inspect_file_for_ingestion

    candidate = tmp_path / "factura.pdf"
    candidate.write_bytes(b"MZfake executable")

    result = inspect_file_for_ingestion(candidate)

    assert result.allowed is False
    assert result.quarantined is True
    assert result.reason == "windows_executable"


def test_queue_selection_splits_heavy_text_and_embedding_work():
    from app.workers.routing import queue_for_document

    pdf = Document(original_filename="scan.pdf", file_hash="a" * 64, extension=".pdf", file_size=1, document_type="plano", status="pending")
    text = Document(original_filename="data.xlsx", file_hash="b" * 64, extension=".xlsx", file_size=1, document_type="excel", status="pending")

    assert queue_for_document(pdf, "extract") == "ocr_heavy"
    assert queue_for_document(text, "extract") == "text_fast"
    assert queue_for_document(text, "reprocess:embeddings") == "embeddings"


def test_access_explain_shows_denied_tag_reason():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        document = _document(db, "contabilidad.pdf", tags=["contabilidad"])
        user = User(email="gestor@local", name="Gestor", password_hash=hash_password("secret"), role="gestor", is_active=True)
        db.add(user)
        db.flush()
        group = AccessGroup(
            name="Gestores",
            permissions_json={"allow_all_hotels": True, "denied_tags": ["contabilidad"]},
        )
        db.add(group)
        db.flush()
        db.add(AccessGroupMember(group_id=group.id, principal_type="user", principal_id=str(user.id)))
        db.commit()
        document_id = document.id
        user_id = user.id

    response = client.get(
        f"/admin/access-explain?principal_type=user&principal_id={user_id}&document_id={document_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is False
    assert any("tag bloqueado" in reason.lower() for reason in payload["reasons"])


def test_document_graph_returns_related_budget_order_and_reference_documents():
    client, sessions = _test_client()
    with sessions() as db:
        token = _admin_token(db)
        source = _document(db, "presupuesto.pdf")
        related = _document(db, "pedido.pdf")
        budget = Budget(
            document_id=source.id,
            budget_number="2026/100",
            client_name="Hotel",
            date=date(2026, 5, 14),
            total_amount=100.0,
            currency="EUR",
            status="aceptado",
            accepted_detected=True,
            confidence=0.9,
        )
        db.add(budget)
        db.flush()
        db.add(BudgetLine(budget_id=budget.id, reference="ABC123", description="Linea", quantity=1, unit="ud", confidence=0.9))
        db.add(Order(document_id=related.id, order_number="P-1", date=date(2026, 5, 15), related_budget_id=budget.id, confidence=0.8))
        db.add(DocumentEntity(document_id=source.id, entity_type="reference", entity_value="ABC123", normalized_value="ABC123"))
        db.add(DocumentEntity(document_id=related.id, entity_type="reference", entity_value="ABC123", normalized_value="ABC123"))
        db.commit()
        source_id = source.id

    response = client.get(f"/admin/documents/{source_id}/graph", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert any(node["document_id"] == source_id for node in payload["nodes"])
    assert any(edge["relation"] in {"budget_order", "shared_reference"} for edge in payload["edges"])


def test_integration_rate_limit_blocks_after_configured_threshold(monkeypatch):
    from app.services.integration_rate_limit import enforce_integration_rate_limit

    class FakeRedis:
        def __init__(self):
            self.values: dict[str, int] = {}
            self.expirations: list[tuple[str, int]] = []

        def incr(self, key: str) -> int:
            self.values[key] = self.values.get(key, 0) + 1
            return self.values[key]

        def expire(self, key: str, seconds: int) -> None:
            self.expirations.append((key, seconds))

    fake = FakeRedis()
    monkeypatch.setattr(settings, "integration_rate_limit_per_minute", 2)
    monkeypatch.setattr("app.services.integration_rate_limit.cache_service._client", fake)

    enforce_integration_rate_limit(client_id=1, technician_id="tech")
    enforce_integration_rate_limit(client_id=1, technician_id="tech")

    try:
        enforce_integration_rate_limit(client_id=1, technician_id="tech")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 429
    else:
        raise AssertionError("rate limit should block the third request")
