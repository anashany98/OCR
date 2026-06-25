import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.routes.admin_helpers import (
    _checklist_item,
    count_where,
)
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, User, WatchedFile
from app.schemas.admin import (
    AdminAlertRead,
    AdminStats,
    ProcessingMetricsRead,
    ProductionChecklistItem,
    ProductionChecklistResponse,
    ProductionReadinessResponse,
    SystemHealthRead,
)
from app.services.cache import cache_service
from app.services.maintenance import build_maintenance_report
from app.services.operations import build_admin_alerts, build_processing_metrics
from app.services.production_readiness import production_readiness
from app.services.queue_control import build_queue_control_status

router = APIRouter(prefix="/admin")


# ---------- health helpers ----------


def _database_health(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _redis_health() -> dict:
    try:
        cache_service.client.ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _disk_health(path: Path) -> dict:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
        free_ratio = usage.free / usage.total if usage.total else 0
        status = "ok" if free_ratio >= 0.10 else "warning"
        return {
            "status": status,
            "path": str(path),
            "total": usage.total,
            "free": usage.free,
            "free_ratio": round(free_ratio, 4),
        }
    except Exception as exc:
        return {"status": "error", "path": str(path), "detail": str(exc)}


def _watcher_health(db: Session) -> dict:
    if not settings.watcher_enabled:
        return {"status": "ok", "enabled": False}
    latest = db.scalar(select(func.max(WatchedFile.updated_at)))
    if not latest:
        return {"status": "ok", "enabled": True, "detail": "No watched files recorded yet"}
    return {"status": "ok", "enabled": True, "last_seen_at": latest.isoformat()}


def _queue_health(db: Session) -> dict:
    status = build_queue_control_status(db)
    if status.backpressure_active:
        return {
            "status": "warning",
            "detail": "Backpressure active",
            "pending_jobs": status.pending_jobs,
        }
    return {
        "status": "ok",
        "ingestion_paused": status.ingestion_paused,
        "pending_jobs": status.pending_jobs,
        "processing_jobs": status.processing_jobs,
    }


def _ai_llm_health() -> dict:
    if not settings.ai_base_url or not settings.ai_model:
        return {"status": "ok", "enabled": False, "detail": "AI LLM not configured"}
    endpoint = f"{settings.ai_base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.ai_api_key:
        headers["Authorization"] = f"Bearer {settings.ai_api_key}"
    try:
        response = httpx.post(
            endpoint,
            headers=headers,
            json={
                "model": settings.ai_model,
                "messages": [{"role": "user", "content": "healthcheck"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout=2.0,
        )
        response.raise_for_status()
        return {"status": "ok", "enabled": True, "endpoint": endpoint, "model": settings.ai_model}
    except Exception as exc:
        return {"status": "warning", "enabled": True, "endpoint": endpoint, "detail": str(exc)}


def _embedding_health() -> dict:
    provider = settings.embedding_provider.lower().strip()
    if provider in {"local", "local_hash"}:
        return {"status": "ok", "enabled": True, "provider": provider, "mode": "deterministic_hash"}
    base_url = settings.embedding_base_url.strip() or settings.ai_base_url.strip()
    if not base_url:
        return {
            "status": "warning",
            "enabled": False,
            "provider": provider,
            "detail": "Embedding base URL not configured",
        }
    endpoint = f"{base_url.rstrip('/')}/embeddings"
    headers = {"Content-Type": "application/json"}
    api_key = settings.embedding_api_key or settings.ai_api_key
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.post(
            endpoint,
            headers=headers,
            json={"model": settings.embedding_model, "input": ["healthcheck"]},
            timeout=settings.embedding_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            return {
                "status": "warning",
                "enabled": True,
                "endpoint": endpoint,
                "detail": "No embedding data returned",
            }
        return {
            "status": "ok",
            "enabled": True,
            "endpoint": endpoint,
            "model": settings.embedding_model,
        }
    except Exception as exc:
        return {"status": "warning", "enabled": True, "endpoint": endpoint, "detail": str(exc)}


def _reranker_health() -> dict:
    """S0.3 — probe the reranker model (BGE-reranker-v2-m3 or
    the configured local model). Returns ``"ok"`` when the model
    is loaded and responsive, ``"warning"`` when it is
    configured but not reachable, ``"ok"`` with ``enabled=False``
    when no reranker is configured.
    """
    if not settings.reranker_local_model and not (
        settings.embedding_base_url or settings.ai_base_url
    ):
        return {"status": "ok", "enabled": False, "detail": "No reranker configured"}
    try:
        from app.services.reranker import rerank_sync
        from app.services.search_service import SearchResult

        candidate = SearchResult(
            document_id=0,
            original_filename="healthcheck",
            document_type="otro",
            status="processed",
            page_number=1,
            block_id=None,
            score=0.5,
            excerpt="healthcheck",
            ocr_confidence=None,
            source_type="text",
            source_path=None,
        )
        result = rerank_sync("test", [candidate], top_k=1)
        if result:
            return {"status": "ok", "enabled": True, "model": settings.reranker_local_model}
        return {"status": "warning", "enabled": True, "detail": "Reranker returned empty result"}
    except Exception as exc:
        return {"status": "warning", "enabled": True, "detail": str(exc)[:200]}


# ---------- routes ----------


@router.get("/stats", response_model=AdminStats)
def stats(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))
) -> AdminStats:
    from app.models import Budget, Order, Plan

    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    accepted_without_order = int(
        db.scalar(
            select(func.count())
            .select_from(Budget)
            .where(Budget.accepted_detected.is_(True))
            .where(Budget.id.not_in(ordered_budget_ids))
        )
        or 0
    )
    plans_without_scale = int(
        db.scalar(select(func.count()).select_from(Plan).where(Plan.has_valid_scale.is_(False)))
        or 0
    )
    return AdminStats(
        documents_total=count_where(db),
        documents_processed=count_where(db, Document.status == "processed"),
        documents_pending=count_where(db, Document.status == "pending"),
        documents_failed=count_where(db, Document.status == "failed"),
        documents_needs_review=count_where(db, Document.status == "needs_review"),
        duplicates=count_where(db, Document.status == "duplicate"),
        ocr_errors=count_where(db, Document.status == "failed"),
        accepted_budgets_without_order=accepted_without_order,
        plans_without_valid_scale=plans_without_scale,
    )


@router.get("/alerts", response_model=list[AdminAlertRead])
def alerts(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))
) -> list:
    return build_admin_alerts(db)


@router.get("/processing-metrics", response_model=ProcessingMetricsRead)
def processing_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_processing_metrics(db)


@router.get("/system/metrics", response_model=ProcessingMetricsRead)
def system_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_processing_metrics(db)


@router.get("/system/health", response_model=SystemHealthRead)
def system_health(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    checks = {
        "database": _database_health(db),
        "redis": _redis_health(),
        "disk_files": _disk_health(settings.files_dir),
        "disk_input": _disk_health(settings.input_dir),
        "watcher": _watcher_health(db),
        "queues": _queue_health(db),
        "ai_llm": _ai_llm_health(),
        "embeddings": _embedding_health(),
        "reranker": _reranker_health(),
    }
    status = "ok" if all(item["status"] == "ok" for item in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@router.get("/production/readiness", response_model=ProductionReadinessResponse)
def production_readiness_endpoint(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return production_readiness(db)


@router.get("/production/checklist", response_model=ProductionChecklistResponse)
def production_checklist(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> ProductionChecklistResponse:
    health = system_health(db=db)
    queue_status = build_queue_control_status(db)
    manifest_ready = bool(settings.ai_provider and settings.ai_base_url is not None)
    items = [
        _checklist_item(
            "database",
            "Base de datos",
            health["checks"]["database"],
            "PostgreSQL responde a consultas basicas.",
            "/admin/system/health",
        ),
        _checklist_item(
            "redis",
            "Redis",
            health["checks"]["redis"],
            "Redis responde para colas, cache y notificaciones.",
            "/admin/system/health",
        ),
        _checklist_item(
            "watcher",
            "Watcher",
            health["checks"]["watcher"],
            "Vigilancia de carpetas configurada para ingesta 24h.",
            "/admin/operations/overview",
        ),
        _checklist_item(
            "disk",
            "Disco",
            health["checks"]["disk_files"],
            "Espacio disponible para originales, previews y OCR.",
            "/admin/system/health",
        ),
        ProductionChecklistItem(
            key="queues",
            title="Colas",
            status="warning" if queue_status.backpressure_active else "ok",
            description=f"Pendientes: {queue_status.pending_jobs}. Procesando: {queue_status.processing_jobs}.",
            action_url="/jobs",
        ),
        ProductionChecklistItem(
            key="backup_runbook",
            title="Backup y restore",
            status="ok"
            if Path("scripts/backup.ps1").exists() and Path("scripts/restore.ps1").exists()
            else "warning",
            description="Runbooks disponibles para PostgreSQL y /data/files.",
            action_url="/admin",
        ),
        ProductionChecklistItem(
            key="integration_manifest",
            title="Manifest IA externa",
            status="ok" if manifest_ready else "warning",
            description="Manifest y tools versionadas para que la IA externa consulte sin SQL.",
            action_url="/integrations/v1/manifest",
        ),
    ]
    return ProductionChecklistResponse(items=items)


@router.get("/maintenance-report")
def maintenance_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_maintenance_report(db)
