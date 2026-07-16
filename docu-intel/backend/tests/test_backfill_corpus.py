from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.commands import backfill_corpus
from app.core.config import settings
from app.database.base import Base
from app.models import Document, DocumentBudgetLink, DocumentOccurrence, Project
from app.services.file_storage import calculate_sha256


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_backfill_links_known_document_and_is_idempotent(tmp_path, monkeypatch):
    sessions = _session_factory()
    root = tmp_path / "2025"
    source = root / "ACME" / "Presupuesto 252536" / "facturas" / "f.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    checkpoint = tmp_path / "backfill-checkpoint.json"
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    monkeypatch.setattr(backfill_corpus, "CHECKPOINT_FILE", checkpoint)

    with sessions() as db:
        db.add(Document(original_filename="f.pdf", source_path=str(source), file_hash="fixture"))
        db.commit()

    first = backfill_corpus.run_backfill(
        dry_run=False,
        full=True,
        session_factory=sessions,
    )
    second = backfill_corpus.run_backfill(
        dry_run=False,
        full=True,
        session_factory=sessions,
    )

    with sessions() as db:
        assert db.scalar(select(func.count(DocumentOccurrence.id))) == 1
        assert db.scalar(select(func.count(DocumentBudgetLink.id))) == 1
        assert db.scalar(select(func.count(Project.id))) == 1

    assert first["occurrences_created"] == 1
    assert second["occurrences_created"] == 0
    assert second["skipped"] == 1
    assert checkpoint.exists()


def test_backfill_dry_run_validates_without_database_or_checkpoint_write(tmp_path, monkeypatch):
    root = tmp_path / "2025"
    source = root / "ACME" / "Presupuesto 252536" / "facturas" / "f.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    checkpoint = tmp_path / "backfill-checkpoint.json"
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    monkeypatch.setattr(backfill_corpus, "CHECKPOINT_FILE", checkpoint)

    result = backfill_corpus.run_backfill(dry_run=True, full=True)

    assert result["validated"] == 1
    assert not checkpoint.exists()


def test_backfill_uses_sha_only_after_exact_path_misses(tmp_path, monkeypatch):
    sessions = _session_factory()
    root = tmp_path / "2025"
    source = root / "ACME" / "Presupuesto 252536" / "facturas" / "f.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    monkeypatch.setattr(settings, "source_corpus_dir", root)
    monkeypatch.setattr(backfill_corpus, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")

    with sessions() as db:
        db.add(
            Document(
                original_filename="f.pdf",
                source_path="/previous/location/f.pdf",
                file_hash=calculate_sha256(source),
            )
        )
        db.commit()

    result = backfill_corpus.run_backfill(dry_run=False, full=True, session_factory=sessions)

    assert result["linked_by_path"] == 0
    assert result["linked_by_sha"] == 1
    assert result["bytes_hashed"] == source.stat().st_size
