"""Controlled lifecycle certification for the project hierarchy.

This deliberately uses a temporary filesystem tree rather than the immutable
production corpus.  It proves the real registration service can resolve both
supported folder shapes and preserve two memberships for one SHA.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base
from app.models import (
    Budget,
    CommunicationMessage,
    CommunicationThread,
    Document,
    DocumentAccessMetadata,
    DocumentBudgetLink,
    DocumentOccurrence,
    ImageAnalysis,
    Invoice,
    Order,
    Project,
)
from app.services.document_registration_service import register_existing_file
from app.services.project_dossier import (
    get_project_dossier,
    list_project_documents,
    resolve_project,
)
from app.services.tenant_access import AccessScope


def _sessions() -> tuple[sessionmaker[Session], bool]:
    """Use PostgreSQL when the certification runner supplies it, SQLite locally."""
    database_url = settings.database_url
    is_postgres = database_url.startswith("postgresql")
    if is_postgres:
        try:
            import psycopg  # noqa: F401
        except ImportError:
            # Developer machines that run the unit suite without the Docker
            # dependency still exercise the same service contract below.
            is_postgres = False
        else:
            engine = create_engine(database_url)
            return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False), True
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False), False


def _register(db: Session, root: Path, relative_path: str, payload: bytes) -> Document:
    source = root / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)
    document, _ = register_existing_file(
        db,
        source=source,
        original_filename=source.name,
        source_path=str(source),
        enqueue=False,
    )
    # The lifecycle below validates hierarchy, not asynchronous extraction.
    # Marking the synthetic fixture searchable lets the second registration
    # exercise the real SHA path that creates a new occurrence.
    document.status = "processed"
    db.commit()
    return document


def _assign_occurrence_access(db: Session) -> None:
    for occurrence, document in db.execute(
        select(DocumentOccurrence, Document).join(Document, DocumentOccurrence.document_id == Document.id)
    ).all():
        metadata = db.scalar(
            select(DocumentAccessMetadata).where(DocumentAccessMetadata.document_id == document.id)
        )
        assert metadata is not None
        metadata.chain_id = occurrence.brand_id
        metadata.hotel_id = occurrence.hotel_id
        metadata.assignment_status = "assigned"
        metadata.assignment_source = "controlled_e2e"
        metadata.tags_json = []
    db.commit()


def test_controlled_project_lifecycle_is_authorized_and_idempotent(tmp_path, monkeypatch):
    sessions, is_postgres = _sessions()
    root = tmp_path / "2025"
    files_dir = tmp_path / "stored"
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    monkeypatch.setattr(settings, "files_dir", files_dir)
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")

    registered: list[tuple[str, bytes]] = [
        ("Marca directa/Presupuesto D-100/presupuestos/presupuesto.txt", b"budget D-100"),
        ("Marca directa/Presupuesto D-100/pedidos/pedido.txt", b"order D-100"),
        ("Marca directa/Presupuesto D-100/facturas/factura.txt", b"invoice D-100"),
        ("Marca directa/Presupuesto D-100/correos/correo.eml", b"From: gestor@example.test\nSubject: D-100"),
        ("Marca directa/Presupuesto D-100/imagenes/instalacion.txt", b"image D-100"),
        ("Marca hotel/Hotel Demo/Presupuesto H-200/presupuestos/presupuesto.txt", b"budget H-200"),
        ("Marca hotel/Hotel Demo/Presupuesto H-200/pedidos/pedido.txt", b"order H-200"),
        ("Marca hotel/Hotel Demo/Presupuesto H-200/facturas/factura.txt", b"invoice H-200"),
        ("Marca hotel/Hotel Demo/Presupuesto H-200/correos/correo.eml", b"From: gestor@example.test\nSubject: H-200"),
        ("Marca hotel/Hotel Demo/Presupuesto H-200/imagenes/instalacion.txt", b"image H-200"),
        ("Marca compartida/Presupuesto C-300/presupuestos/compartido.txt", b"same physical bytes"),
        ("Marca compartida/Presupuesto C-301/presupuestos/compartido.txt", b"same physical bytes"),
    ]

    try:
        with sessions() as db:
            documents = {
                relative_path: _register(db, root, relative_path, payload)
                for relative_path, payload in registered
            }
            _assign_occurrence_access(db)

            direct_project = db.scalar(
                select(Project).join(Project.primary_budget_scope).where(
                    Project.primary_budget_scope.has(budget_code="D-100")
                )
            )
            hotel_project = db.scalar(
                select(Project).join(Project.primary_budget_scope).where(
                    Project.primary_budget_scope.has(budget_code="H-200")
                )
            )
            assert direct_project is not None and direct_project.hotel_id is None
            assert hotel_project is not None and hotel_project.hotel_id is not None

            direct_documents = {
                path.rsplit("/", 1)[0].split("/")[-1]: document
                for path, document in documents.items()
                if path.startswith("Marca directa/")
            }
            budget_document = direct_documents["presupuestos"]
            order_document = direct_documents["pedidos"]
            invoice_document = direct_documents["facturas"]
            email_document = direct_documents["correos"]
            image_document = direct_documents["imagenes"]
            db.add_all([
                Budget(document_id=budget_document.id, budget_number="D-100", date=date(2026, 7, 1), total_amount=100.0, currency="EUR"),
                Order(document_id=order_document.id, order_number="D-100-O", date=date(2026, 7, 2), total_amount=80.0, currency="EUR"),
                Invoice(document_id=invoice_document.id, invoice_number="D-100-F", date=date(2026, 7, 3), total_amount=75.0, currency="EUR"),
            ])
            db.flush()
            thread = CommunicationThread(
                subject="Seguimiento D-100",
                project_id=direct_project.id,
                budget_scope_id=direct_project.primary_budget_scope_id,
                message_count=1,
            )
            db.add(thread)
            db.flush()
            db.add_all([
                CommunicationMessage(
                    thread_id=thread.id,
                    document_id=email_document.id,
                    from_email="gestor@example.test",
                    subject="Seguimiento D-100",
                    body_text="Instalacion prevista.",
                ),
                ImageAnalysis(
                    document_id=image_document.id,
                    labels_json=["instalacion"],
                    description="Instalacion controlada",
                    model_name="fixture",
                    model_version="1",
                    confidence=1.0,
                ),
            ])
            db.commit()

            # Re-ingesting every exact source path must not create a document,
            # occurrence, project, or link duplicate.
            before = {
                "documents": db.scalar(select(func.count(Document.id))),
                "occurrences": db.scalar(select(func.count(DocumentOccurrence.id))),
                "links": db.scalar(select(func.count(DocumentBudgetLink.id))),
                "projects": db.scalar(select(func.count(Project.id))),
            }
            for relative_path, payload in registered:
                repeated = _register(db, root, relative_path, payload)
                assert repeated.id == documents[relative_path].id
            after = {
                "documents": db.scalar(select(func.count(Document.id))),
                "occurrences": db.scalar(select(func.count(DocumentOccurrence.id))),
                "links": db.scalar(select(func.count(DocumentBudgetLink.id))),
                "projects": db.scalar(select(func.count(Project.id))),
            }
            assert after == before

            shared = list(db.scalars(select(Document).where(Document.file_hash == documents[
                "Marca compartida/Presupuesto C-300/presupuestos/compartido.txt"
            ].file_hash)).all())
            assert len(shared) == 1
            shared_occurrences = list(db.scalars(
                select(DocumentOccurrence).where(DocumentOccurrence.document_id == shared[0].id)
            ).all())
            assert len(shared_occurrences) == 2
            assert len({item.project_id for item in shared_occurrences}) == 2
            assert db.scalar(
                select(func.count(DocumentBudgetLink.id)).where(DocumentBudgetLink.document_id == shared[0].id)
            ) == 2

            allowed = AccessScope(
                principal_type="user",
                principal_id="certifier",
                chain_ids={direct_project.brand_id},
                can_view_prices=True,
            )
            dossier = get_project_dossier(db, direct_project.id, access_scope=allowed)
            assert dossier.total_documents == 5
            assert dossier.occurrence_count == 5
            assert dossier.budget_total == 100.0
            assert dossier.order_total == 80.0
            assert dossier.invoice_total == 75.0
            assert dossier.thread_count == 1 and dossier.message_count == 1 and dossier.image_count == 1
            assert len(list_project_documents(db, direct_project.id, access_scope=allowed)) == 5
            assert resolve_project(db, budget_code="D-100", access_scope=allowed) == [direct_project]

            forbidden = AccessScope(principal_type="user", principal_id="foreign")
            assert resolve_project(db, budget_code="D-100", access_scope=forbidden) == []
            with pytest.raises(PermissionError):
                get_project_dossier(db, direct_project.id, access_scope=forbidden)
    finally:
        if is_postgres:
            # The runner owns an isolated database.  Keep a failed fixture
            # inspectable only until the runner drops that database.
            with sessions() as db:
                db.rollback()
