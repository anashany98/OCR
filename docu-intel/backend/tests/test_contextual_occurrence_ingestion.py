from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.base import Base
from app.models import Document
from app.models.project import DocumentBudgetLink
from app.services.document_registration_service import _create_occurrence


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
