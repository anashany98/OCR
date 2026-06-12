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
    DocumentChunk,
    DocumentEntity,
    ExtractionJob,
    Hotel,
    HotelChain,
    IngestionEvent,
    Order,
    User,
    WatchedFile,
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


def test_storage_integrity_reports_missing_and_orphan_files(tmp_path, monkeypatch):
    from app.services.production_readiness import storage_integrity

    files_dir = tmp_path / "files"
    present_relative = Path("aa") / "present.pdf"
    orphan_relative = Path("cc") / "orphan.txt"
    present_path = files_dir / present_relative
    orphan_path = files_dir / orphan_relative
    present_path.parent.mkdir(parents=True)
    orphan_path.parent.mkdir(parents=True)
    present_path.write_bytes(b"stored")
    orphan_path.write_bytes(b"orphan")
    monkeypatch.setattr(settings, "files_dir", files_dir)

    sessions = _session_factory()
    with sessions() as db:
        db.add(
            Document(
                original_filename="present.pdf",
                stored_filename=str(present_relative),
                source_path="/data/input/present.pdf",
                file_hash="1" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=7,
                document_type="presupuesto",
                status="processed",
            )
        )
        db.add(
            Document(
                original_filename="missing.pdf",
                stored_filename=str(Path("bb") / "missing.pdf"),
                source_path="/data/input/missing.pdf",
                file_hash="2" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=7,
                document_type="presupuesto",
                status="processed",
            )
        )
        db.commit()

        result = storage_integrity(db, limit=10)

    assert result["checked_documents"] == 2
    assert result["missing_files"] == 1
    assert result["orphan_files"] == 1
    assert result["missing_file_samples"] == [{"document_id": 2, "stored_filename": str(Path("bb") / "missing.pdf")}]
    assert result["orphan_file_samples"] == [str(orphan_relative)]


def test_storage_integrity_accepts_valid_hash_layout_without_false_positives(tmp_path, monkeypatch):
    from app.services.production_readiness import storage_integrity

    files_dir = tmp_path / "files"
    stored_relative = Path("ab") / "cd" / f"{'1' * 64}.pdf"
    stored_path = files_dir / stored_relative
    stored_path.parent.mkdir(parents=True)
    stored_path.write_bytes(b"stored")
    monkeypatch.setattr(settings, "files_dir", files_dir)

    sessions = _session_factory()
    with sessions() as db:
        db.add(
            Document(
                original_filename="valid-hash-layout.pdf",
                stored_filename=str(stored_relative),
                source_path="/data/input/valid-hash-layout.pdf",
                file_hash="1" * 64,
                mime_type="application/pdf",
                extension=".pdf",
                file_size=6,
                document_type="presupuesto",
                status="processed",
            )
        )
        db.commit()

        result = storage_integrity(db, limit=10)

    assert result["checked_documents"] == 1
    assert result["missing_files"] == 0
    assert result["orphan_files"] == 0
    assert result["missing_file_samples"] == []
    assert result["orphan_file_samples"] == []


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


# ---------------------------------------------------------------------------
# SEC-ADMIN-1 — scope the operational admin surfaces that the
# original audit flagged as leaking filesystem paths and documents
# outside the caller's access scope. Covers:
#   * GET /admin/watched-files
#   * GET /admin/ingestion-events
#   * GET /admin/documents/needs-re-embedding
#   * POST /admin/documents/{id}/re-embed
# ---------------------------------------------------------------------------


def _scoped_user_token(db: Session, *, role: str, hotel_ids: list[int] | None = None) -> tuple[str, User]:
    """Create a non-admin user with a single AccessGroup that grants
    access to ``hotel_ids`` (or, when omitted, no hotels at all → empty
    scope). Returns a JWT for the user.
    """
    user = User(
        email=f"{role}@local",
        name=role.title(),
        password_hash=hash_password("secret"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    permissions: dict = {}
    if hotel_ids:
        permissions["hotel_ids"] = hotel_ids
    group = AccessGroup(name=f"{role} group", permissions_json=permissions)
    db.add(group)
    db.flush()
    db.add(
        AccessGroupMember(
            group_id=group.id,
            principal_type="user",
            principal_id=str(user.id),
        )
    )
    db.flush()
    return create_access_token(str(user.id)), user


def test_admin_watched_files_filters_by_scope_and_redacts_paths():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token = _admin_token(db)
        scoped_token, _ = _scoped_user_token(db, role="gestor", hotel_ids=None)
        # Two documents: one with hotel assigned, one without.
        doc_in_scope = _document(db, "in_scope.pdf")
        doc_out_of_scope = _document(db, "out_of_scope.pdf")
        db.add(
            WatchedFile(
                path="/data/input/presupuestos/245745/in_scope.pdf",
                status="processed",
                document_id=doc_in_scope.id,
            )
        )
        db.add(
            WatchedFile(
                path="/data/input/presupuestos/999999/out_of_scope.pdf",
                status="processed",
                document_id=doc_out_of_scope.id,
            )
        )
        # Unlinked watched file (no document yet) — must stay visible.
        db.add(
            WatchedFile(
                path="/data/input/_staging/pending.pdf",
                status="detected",
                document_id=None,
            )
        )
        db.commit()

    # Admin sees everything with full paths.
    admin_response = client.get(
        "/admin/watched-files",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200
    admin_paths = {row["path"] for row in admin_response.json()}
    assert "/data/input/presupuestos/245745/in_scope.pdf" in admin_paths
    assert "/data/input/presupuestos/999999/out_of_scope.pdf" in admin_paths

    # Scoped user (no hotel access) sees only the unlinked row, and
    # the path is redacted to its filename.
    scoped_response = client.get(
        "/admin/watched-files",
        headers={"Authorization": f"Bearer {scoped_token}"},
    )
    assert scoped_response.status_code == 200
    scoped_rows = scoped_response.json()
    scoped_paths = {row["path"] for row in scoped_rows}
    assert scoped_paths == {"pending.pdf"}
    # The two in-scope documents (one assigned to a hotel they cannot
    # access) must be filtered out entirely.
    assert all("245745" not in row["path"] for row in scoped_rows)
    assert all("999999" not in row["path"] for row in scoped_rows)


def test_admin_ingestion_events_filters_by_scope_and_redacts_source_paths():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token = _admin_token(db)
        scoped_token, _ = _scoped_user_token(db, role="auditor", hotel_ids=None)
        doc_in = _document(db, "event_in.pdf")
        doc_out = _document(db, "event_out.pdf")
        db.add(
            IngestionEvent(
                event_type="detected",
                source_path="/data/input/pedidos/245745/event_in.pdf",
                document_id=doc_in.id,
            )
        )
        db.add(
            IngestionEvent(
                event_type="processed",
                source_path="/data/input/pedidos/999999/event_out.pdf",
                document_id=doc_out.id,
            )
        )
        db.commit()

    admin_response = client.get(
        "/admin/ingestion-events",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200
    admin_paths = {row["source_path"] for row in admin_response.json()}
    assert "/data/input/pedidos/245745/event_in.pdf" in admin_paths
    assert "/data/input/pedidos/999999/event_out.pdf" in admin_paths

    scoped_response = client.get(
        "/admin/ingestion-events",
        headers={"Authorization": f"Bearer {scoped_token}"},
    )
    assert scoped_response.status_code == 200
    scoped_rows = scoped_response.json()
    # The auditor has no hotel access, so the two linked events are
    # filtered out entirely. No rows should remain.
    assert scoped_rows == []


def test_admin_needs_reembedding_filters_by_scope():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token = _admin_token(db)
        scoped_token, _ = _scoped_user_token(db, role="gestor", hotel_ids=None)
        doc_in = _document(db, "reembed_in.pdf")
        doc_out = _document(db, "reembed_out.pdf")
        for document, n_needing in ((doc_in, 2), (doc_out, 3)):
            for i in range(4):
                db.add(
                    DocumentChunk(
                        document_id=document.id,
                        page_number=1,
                        chunk_text=f"chunk {i}",
                        embedding=None if i < n_needing else [0.0] * 1024,
                        needs_reembedding=(i < n_needing),
                        token_count=2,
                    )
                )
        db.commit()

    admin_response = client.get(
        "/admin/documents/needs-re-embedding",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200
    admin_filenames = {row["original_filename"] for row in admin_response.json()}
    assert "reembed_in.pdf" in admin_filenames
    assert "reembed_out.pdf" in admin_filenames

    scoped_response = client.get(
        "/admin/documents/needs-re-embedding",
        headers={"Authorization": f"Bearer {scoped_token}"},
    )
    assert scoped_response.status_code == 200
    scoped_filenames = {row["original_filename"] for row in scoped_response.json()}
    # The scoped gestor cannot see either document, so the list is
    # empty even though both documents have pending chunks.
    assert scoped_filenames == set()


def test_admin_reembed_endpoint_requires_can_access_document():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token = _admin_token(db)
        scoped_token, _ = _scoped_user_token(db, role="gestor", hotel_ids=None)
        doc_in = _document(db, "reembed_target.pdf")
        # Give the doc at least one chunk so reembed would do
        # something if the scope check were missing.
        db.add(
            DocumentChunk(
                document_id=doc_in.id,
                page_number=1,
                chunk_text="hello",
                embedding=None,
                needs_reembedding=True,
                token_count=1,
            )
        )
        db.commit()
        doc_id = doc_in.id

    # Admin can re-embed anything.
    admin_response = client.post(
        f"/admin/documents/{doc_id}/re-embed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200

    # Scoped gestor cannot re-embed a document outside their scope:
    # we return 404 (not 403) so we do not leak the existence of the
    # document.
    scoped_response = client.post(
        f"/admin/documents/{doc_id}/re-embed",
        headers={"Authorization": f"Bearer {scoped_token}"},
    )
    assert scoped_response.status_code == 404
    assert scoped_response.json()["detail"] == "Document not found"


def test_admin_reembed_endpoint_returns_404_for_missing_document():
    client, sessions = _test_client()
    with sessions() as db:
        admin_token = _admin_token(db)
        db.commit()
    response = client.post(
        "/admin/documents/9999999/re-embed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404
