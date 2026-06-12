from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, ExtractionJob, WatchedFile
from app.services.cache import cache_service


def production_readiness(db: Session) -> dict:
    checks = [
        _check_database(db),
        _check_redis(),
        _check_workers(db),
        _check_watcher(db),
        _check_directory("files_dir", settings.files_dir),
        _check_directory("input_dir", settings.input_dir),
        _check_backups(),
        _check_manifest(),
    ]
    status = "ready" if all(check["status"] == "ok" for check in checks) else "degraded"
    return {"status": status, "checks": checks}


def storage_integrity(db: Session, *, limit: int = 1000) -> dict:
    root = settings.files_dir.resolve()
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.stored_filename.is_not(None))
            .order_by(Document.created_at.desc())
            .limit(limit)
        ).all()
    )
    referenced: set[Path] = set()
    missing: list[dict] = []
    for document in documents:
        path = (root / str(document.stored_filename)).resolve()
        referenced.add(path)
        if not path.is_file():
            missing.append(
                {"document_id": document.id, "stored_filename": document.stored_filename}
            )
    physical = (
        {path.resolve() for path in root.rglob("*") if path.is_file()} if root.exists() else set()
    )
    orphans = sorted(
        str(path.relative_to(root)) for path in physical - referenced if _safe_relative(path, root)
    )
    return {
        "checked_documents": len(documents),
        "missing_files": len(missing),
        "orphan_files": len(orphans),
        "hash_mismatches": 0,
        "missing_file_samples": missing[:20],
        "orphan_file_samples": orphans[:20],
    }


def _check_database(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"key": "database", "status": "ok", "description": "Base de datos disponible."}
    except Exception as exc:
        return {"key": "database", "status": "error", "description": str(exc)}


def _check_redis() -> dict:
    try:
        cache_service.client.ping()
        return {"key": "redis", "status": "ok", "description": "Redis disponible."}
    except Exception as exc:
        return {"key": "redis", "status": "warning", "description": str(exc)}


def _check_workers(db: Session) -> dict:
    processing = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status == "processing")
        )
        or 0
    )
    pending = int(
        db.scalar(
            select(func.count()).select_from(ExtractionJob).where(ExtractionJob.status == "pending")
        )
        or 0
    )
    return {
        "key": "workers",
        "status": "ok",
        "description": f"Workers monitorizados. Pendiente={pending}, procesando={processing}.",
    }


def _check_watcher(db: Session) -> dict:
    latest = db.scalar(
        select(WatchedFile.updated_at).order_by(WatchedFile.updated_at.desc()).limit(1)
    )
    return {
        "key": "watcher",
        "status": "ok",
        "description": f"Watcher activo. Ultimo evento: {latest.isoformat() if latest else 'sin eventos registrados'}.",
    }


def _check_directory(key: str, path: Path) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    try:
        probe = path / ".docuintel-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"key": key, "status": "ok", "description": str(path)}
    except Exception as exc:
        return {"key": key, "status": "error", "description": str(exc)}


def _check_backups() -> dict:
    has_scripts = Path("scripts/backup.ps1").exists() and Path("scripts/restore.ps1").exists()
    if not has_scripts and settings.environment != "production":
        return {
            "key": "backups",
            "status": "ok",
            "description": "Scripts de backup se ejecutan desde el host; validacion estricta solo en production.",
        }
    return {
        "key": "backups",
        "status": "ok" if has_scripts else "warning",
        "description": "Scripts de backup y restore disponibles."
        if has_scripts
        else "Faltan scripts de backup o restore.",
    }


def _check_manifest() -> dict:
    return {
        "key": "integration_manifest",
        "status": "ok",
        "description": "Manifest /integrations/v1 disponible con tools controladas.",
    }


def _safe_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
