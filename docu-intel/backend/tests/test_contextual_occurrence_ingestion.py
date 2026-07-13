from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.base import Base
from app.models import Document, DocumentEntity
from app.models.project import DocumentBudgetLink, DocumentOccurrence
from app.services.document_registration_service import _create_occurrence, register_existing_file


def test_occurrence_creates_contextual_project_and_budget_link(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    root = tmp_path / "2025"
    source = root / "ACME" / "Hotel A" / "Presupuesto 252536" / "facturas" / "f.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test")
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    doc = Document(original_filename="f.pdf", file_hash="hash", source_path=str(source))
    db.add(doc)
    db.flush()

    occurrence = _create_occurrence(db, doc, source, str(source))
    link = db.scalar(select(DocumentBudgetLink).where(DocumentBudgetLink.document_id == doc.id))

    assert occurrence is not None
    assert occurrence.project_id is not None
    assert occurrence.budget_scope_id == doc.budget_scope_id
    assert link is not None and link.occurrence_id == occurrence.id
    assert occurrence.association_status == "folder_only"
    assert link.status == "folder_only"


def test_occurrence_keeps_conflicting_folder_and_content_budget_for_review(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    root = tmp_path / "2025"
    source = root / "ACME" / "Presupuesto 252536" / "facturas" / "f.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test")
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    doc = Document(original_filename="f.pdf", file_hash="hash", source_path=str(source))
    db.add(doc)
    db.flush()
    db.add(
        DocumentEntity(
            document_id=doc.id,
            entity_type="budget_number",
            entity_value="252537",
            confidence=0.99,
        )
    )
    db.flush()

    occurrence = _create_occurrence(db, doc, source, str(source))
    link = db.scalar(select(DocumentBudgetLink).where(DocumentBudgetLink.document_id == doc.id))

    assert occurrence is not None
    assert occurrence.association_status == "conflict"
    assert occurrence.folder_budget_code == "252536"
    assert occurrence.document_budget_code == "252537"
    assert occurrence.resolved_budget_code is None
    assert link is not None and link.status == "conflict"


def test_changed_sha_at_same_path_updates_live_occurrence_without_losing_old_document(
    tmp_path, monkeypatch
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    root = tmp_path / "2025"
    source = root / "ACME" / "Presupuesto 252536" / "facturas" / "f.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"version one")
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")

    first, _ = register_existing_file(
        db,
        source=source,
        source_path=str(source),
        original_filename=source.name,
        enqueue=False,
    )
    source.write_bytes(b"version two")
    second, _ = register_existing_file(
        db,
        source=source,
        source_path=str(source),
        original_filename=source.name,
        enqueue=False,
    )
    occurrence = db.scalar(
        select(DocumentOccurrence).where(DocumentOccurrence.source_path == str(source))
    )

    assert second.id != first.id
    assert occurrence is not None and occurrence.document_id == second.id
    assert db.get(Document, first.id) is not None


def test_outside_corpus_root_never_creates_project_membership(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(settings, "source_corpus_dir", tmp_path / "2025")
    source = tmp_path / "input" / "ACME" / "Presupuesto 252536" / "f.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test")
    doc = Document(original_filename="f.pdf", file_hash="hash", source_path=str(source))
    db.add(doc)
    db.flush()

    assert _create_occurrence(db, doc, source, str(source)) is None
