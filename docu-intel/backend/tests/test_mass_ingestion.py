from __future__ import annotations

import os
import time
from collections.abc import Generator
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base
from app.ingestion.scanner import scan_input_folders
from app.models import Document, ExtractionJob, IngestionEvent, WatchedFile
from app.services.file_storage import calculate_sha256, copy_to_storage


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _old_enough(path: Path, seconds: int = 120) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_scan_skips_files_until_they_are_stable(tmp_path, monkeypatch):
    sessions = _session_factory()
    input_dir = tmp_path / "input"
    pending_file = input_dir / "presupuestos" / "copiando.pdf"
    pending_file.parent.mkdir(parents=True)
    pending_file.write_bytes(b"todavia copiando")

    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 3600)

    with sessions() as db:
        result = scan_input_folders(db, enqueue=False)
        documents = list(db.scalars(select(Document)).all())

    assert result["unstable"] == 1
    assert result["registered"] == 0
    assert documents == []


def test_scan_registers_stable_files_from_input_folders(tmp_path, monkeypatch):
    sessions = _session_factory()
    input_dir = tmp_path / "input"
    stable_file = input_dir / "pedidos" / "pedido-1.pdf"
    stable_file.parent.mkdir(parents=True)
    stable_file.write_bytes(b"pedido estable")
    _old_enough(stable_file)

    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 1)
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")

    with sessions() as db:
        result = scan_input_folders(db, enqueue=False)
        document = db.scalar(select(Document).where(Document.original_filename == "pedido-1.pdf"))

    assert result["registered"] == 1
    assert result["unstable"] == 0
    assert document is not None
    assert document.source_path == str(stable_file)


def test_file_storage_auto_uses_hardlink_when_available(tmp_path, monkeypatch):
    source = tmp_path / "origen.pdf"
    source.write_bytes(b"contenido grande")
    file_hash = calculate_sha256(source)
    calls: list[tuple[str, str]] = []

    def fake_link(src, dst):
        calls.append((str(src), str(dst)))
        Path(dst).write_bytes(Path(src).read_bytes())

    monkeypatch.setattr(os, "link", fake_link)

    relative_path = copy_to_storage(source, tmp_path / "files", file_hash, ".pdf", strategy="auto")

    assert calls
    assert (tmp_path / "files" / relative_path).read_bytes() == b"contenido grande"


def test_file_storage_auto_falls_back_to_copy_when_hardlink_fails(tmp_path, monkeypatch):
    source = tmp_path / "origen.pdf"
    source.write_bytes(b"contenido")
    file_hash = calculate_sha256(source)

    def fail_link(src, dst):
        raise OSError("different device")

    monkeypatch.setattr(os, "link", fail_link)

    relative_path = copy_to_storage(source, tmp_path / "files", file_hash, ".pdf", strategy="auto")

    assert (tmp_path / "files" / relative_path).read_bytes() == b"contenido"


def test_pending_file_registry_releases_paths_after_settle_delay():
    from app.ingestion.watcher import PendingFileRegistry

    pending = PendingFileRegistry()
    pending.add(Path("/data/input/pedidos/a.pdf"), now=10.0)
    pending.add(Path("/data/input/pedidos/b.pdf"), now=20.0)

    assert pending.ready_paths(now=24.0, settle_seconds=5.0, limit=10) == [Path("/data/input/pedidos/a.pdf")]
    assert pending.ready_paths(now=25.0, settle_seconds=5.0, limit=10) == [
        Path("/data/input/pedidos/a.pdf"),
        Path("/data/input/pedidos/b.pdf"),
    ]


def test_scan_mixed_batch_records_auditable_rows(tmp_path, monkeypatch):
    sessions = _session_factory()
    input_dir = tmp_path / "input"
    files_dir = tmp_path / "files"
    valid_file = input_dir / "pedidos" / "valid.txt"
    ignored_temp = input_dir / "pedidos" / "ignored.tmp"
    not_allowed = input_dir / "pedidos" / "not-allowed.exe"
    unstable_file = input_dir / "pedidos" / "unstable.txt"
    same_hash = input_dir / "pedidos" / "same.txt"
    changed_hash = input_dir / "pedidos" / "changed.txt"
    for path, content in [
        (valid_file, b"valid"),
        (ignored_temp, b"temp"),
        (not_allowed, b"not allowed"),
        (unstable_file, b"unstable"),
        (same_hash, b"same"),
        (changed_hash, b"changed-new"),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for path in [valid_file, ignored_temp, not_allowed, same_hash, changed_hash]:
        _old_enough(path)

    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", files_dir)
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 60)
    monkeypatch.setattr(settings, "allowed_file_extensions", [".txt"])
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")

    with sessions() as db:
        db.add(
            Document(
                original_filename="same.txt",
                source_path=str(same_hash),
                file_hash=calculate_sha256(same_hash),
                extension=".txt",
                file_size=same_hash.stat().st_size,
                document_type="texto",
                status="pending",
                quality_status="pending",
            )
        )
        db.add(
            Document(
                original_filename="changed.txt",
                source_path=str(changed_hash),
                file_hash="0" * 64,
                extension=".txt",
                file_size=1,
                document_type="texto",
                status="pending",
                quality_status="pending",
            )
        )
        db.commit()

        result = scan_input_folders(db, enqueue=False)
        watched = {row.path: row.status for row in db.scalars(select(WatchedFile)).all()}
        events = {(row.source_path, row.event_type) for row in db.scalars(select(IngestionEvent)).all()}

    assert result["registered"] == 2
    assert result["ignored"] == 1
    assert result["unstable"] == 1
    assert result["skipped"] == 1
    assert watched[str(valid_file)] == "registered"
    assert watched[str(not_allowed)] == "ignored"
    assert watched[str(unstable_file)] == "unstable"
    assert watched[str(same_hash)] == "skipped"
    assert watched[str(changed_hash)] == "registered"
    assert str(ignored_temp) not in watched
    assert (str(changed_hash), "modified") in events
    assert (str(changed_hash), "registered") in events


def test_scan_same_source_path_changed_hash_registers_new_pending_document(tmp_path, monkeypatch):
    sessions = _session_factory()
    input_dir = tmp_path / "input"
    changed_file = input_dir / "pedidos" / "changed.txt"
    changed_file.parent.mkdir(parents=True)
    changed_file.write_bytes(b"new content")
    _old_enough(changed_file)

    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 1)
    monkeypatch.setattr(settings, "allowed_file_extensions", [".txt"])
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")

    with sessions() as db:
        db.add(
            Document(
                original_filename="changed.txt",
                source_path=str(changed_file),
                file_hash="1" * 64,
                extension=".txt",
                file_size=1,
                document_type="texto",
                status="processed",
                quality_status="processed",
            )
        )
        db.commit()

        result = scan_input_folders(db, enqueue=False)
        documents = list(db.scalars(select(Document).where(Document.source_path == str(changed_file))).all())
        job = db.scalar(select(ExtractionJob).join(Document).where(Document.file_hash == calculate_sha256(changed_file)))
        event_types = [
            row.event_type
            for row in db.scalars(select(IngestionEvent).where(IngestionEvent.source_path == str(changed_file))).all()
        ]

    assert result["registered"] == 1
    assert len(documents) == 2
    assert job is not None
    assert "modified" in event_types
    assert "registered" in event_types


def test_scan_backpressure_records_event_without_registering_document(tmp_path, monkeypatch):
    sessions = _session_factory()
    input_dir = tmp_path / "input"
    candidate = input_dir / "pedidos" / "blocked.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"blocked")
    _old_enough(candidate)

    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 1)
    monkeypatch.setattr(settings, "allowed_file_extensions", [".txt"])
    monkeypatch.setattr(settings, "ingestion_max_pending_jobs", 1)

    with sessions() as db:
        existing = Document(
            original_filename="existing.txt",
            file_hash="2" * 64,
            extension=".txt",
            file_size=1,
            document_type="texto",
            status="pending",
            quality_status="pending",
        )
        db.add(existing)
        db.flush()
        db.add(ExtractionJob(document_id=existing.id, job_type="extract", status="pending"))
        db.commit()

        result = scan_input_folders(db, enqueue=False)
        document = db.scalar(select(Document).where(Document.source_path == str(candidate)))
        watched = db.scalar(select(WatchedFile).where(WatchedFile.path == str(candidate)))
        event = db.scalar(select(IngestionEvent).where(IngestionEvent.source_path == str(candidate)))

    assert result["backpressure"] == 1
    assert document is None
    assert watched.status == "backpressure"
    assert event.event_type == "backpressure"


def test_scan_pause_records_audit_and_resume_registers(tmp_path, monkeypatch):
    sessions = _session_factory()
    input_dir = tmp_path / "input"
    candidate = input_dir / "pedidos" / "paused.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"paused")
    _old_enough(candidate)

    monkeypatch.setattr(settings, "input_dir", input_dir)
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "ingestion_stable_seconds", 1)
    monkeypatch.setattr(settings, "allowed_file_extensions", [".txt"])
    monkeypatch.setattr(settings, "file_storage_strategy", "copy")

    with sessions() as db:
        monkeypatch.setattr("app.ingestion.scanner.is_ingestion_paused", lambda: True)
        paused_result = scan_input_folders(db, enqueue=False)
        assert db.scalar(select(Document).where(Document.source_path == str(candidate))) is None
        watched = db.scalar(select(WatchedFile).where(WatchedFile.path == str(candidate)))
        assert watched.status == "paused"

        monkeypatch.setattr("app.ingestion.scanner.is_ingestion_paused", lambda: False)
        resumed_result = scan_input_folders(db, enqueue=False)
        document = db.scalar(select(Document).where(Document.source_path == str(candidate)))
        event_types = [
            row.event_type
            for row in db.scalars(select(IngestionEvent).where(IngestionEvent.source_path == str(candidate))).all()
        ]

    assert paused_result["paused"] == 1
    assert resumed_result["registered"] == 1
    assert document is not None
    assert "paused" in event_types
    assert "registered" in event_types


def test_watcher_retry_exhaustion_stops_requeueing_and_records_failed(tmp_path, monkeypatch):
    from app.ingestion import watcher

    sessions = _session_factory()
    candidate = tmp_path / "input" / "pedidos" / "bad.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"bad")
    pending = watcher.PendingFileRegistry(MAX_RETRIES=2)
    pending.add(candidate, now=0.0)

    monkeypatch.setattr(settings, "watcher_settle_seconds", 0)
    monkeypatch.setattr(settings, "watcher_max_files_per_tick", 10)
    monkeypatch.setattr(watcher, "ingest_path_if_ready", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with sessions() as db:
        first = watcher.process_pending_paths(db, pending, enqueue=False)
        second = watcher.process_pending_paths(db, pending, enqueue=False)
        failed_events = list(db.scalars(select(IngestionEvent).where(IngestionEvent.source_path == str(candidate))).all())
        watched = db.scalar(select(WatchedFile).where(WatchedFile.path == str(candidate)))

    assert first["failed"] == 1
    assert second["failed"] == 1
    assert len(pending) == 0
    assert len(failed_events) == 2
    assert watched.status == "failed"
    assert watched.error_message == "boom"
