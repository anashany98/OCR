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
from app.models import Document
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
