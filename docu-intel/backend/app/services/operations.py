from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog, Budget, Document, ExtractionJob, Order, Plan, User
from app.services.audit import write_audit
from app.services.document_service import reprocess_document


@dataclass(frozen=True)
class BulkReprocessFilters:
    status: str | None = None
    document_type: str | None = None
    source_path_contains: str | None = None
    ids: list[int] | None = None
    quality_flags: list[str] | None = None
    limit: int = 100
    mode: Literal["full", "ocr", "text", "classification", "entities", "chunks", "embeddings"] = (
        "full"
    )


@dataclass(frozen=True)
class BulkReprocessResult:
    matched: int
    enqueued: int
    skipped: int
    job_ids: list[int]
    mode: str


@dataclass(frozen=True)
class AlertDefinition:
    key: str
    title: str
    description: str
    severity: Literal["critical", "warning", "info"]
    action_url: str


@dataclass(frozen=True)
class AdminAlert:
    key: str
    title: str
    description: str
    severity: str
    count: int
    action_url: str


ALERT_DEFINITIONS: tuple[AlertDefinition, ...] = (
    AlertDefinition(
        key="accepted_budgets_without_order",
        title="Presupuestos aceptados sin pedido",
        description="Presupuestos marcados como aceptados que no tienen pedido relacionado.",
        severity="warning",
        action_url="/budgets",
    ),
    AlertDefinition(
        key="orders_without_budget",
        title="Pedidos sin presupuesto relacionado",
        description="Pedidos sin enlace a presupuesto; conviene revisar relación documental.",
        severity="warning",
        action_url="/orders",
    ),
    AlertDefinition(
        key="ocr_review_documents",
        title="Documentos con OCR/error para revisar",
        description="Documentos fallidos o con estado de revisión humana.",
        severity="critical",
        action_url="/documents",
    ),
    AlertDefinition(
        key="plans_without_valid_scale",
        title="Planos sin escala válida",
        description="Planos donde no se puede convertir geometría a metros de forma fiable.",
        severity="warning",
        action_url="/plans",
    ),
    AlertDefinition(
        key="duplicate_documents",
        title="Documentos duplicados",
        description="Archivos con SHA256 repetido registrados como duplicados.",
        severity="info",
        action_url="/documents",
    ),
    AlertDefinition(
        key="failed_jobs",
        title="Jobs fallidos",
        description="Trabajos de extracción o reprocesado terminados en error.",
        severity="critical",
        action_url="/jobs",
    ),
    AlertDefinition(
        key="low_quality_documents",
        title="Documentos procesados con baja calidad",
        description="Documentos procesados pero con OCR bajo, texto insuficiente o campos críticos pendientes.",
        severity="warning",
        action_url="/ocr-review",
    ),
    AlertDefinition(
        key="disk_low",
        title="Disco bajo",
        description="El volumen de documentos u origen está por debajo del 10% libre.",
        severity="critical",
        action_url="/admin",
    ),
    AlertDefinition(
        key="queue_backpressure",
        title="Cola cerca del límite",
        description="Los jobs pendientes/procesando han alcanzado el límite configurado de backpressure.",
        severity="warning",
        action_url="/admin",
    ),
)


def normalize_bulk_reprocess_filters(filters: BulkReprocessFilters) -> BulkReprocessFilters:
    limit = max(1, min(filters.limit or 100, 200))
    normalized = replace(
        filters,
        status=_clean(filters.status),
        document_type=_clean(filters.document_type),
        source_path_contains=_clean(filters.source_path_contains),
        ids=[int(item) for item in filters.ids or []] or None,
        limit=limit,
    )
    if not any(
        [
            normalized.status,
            normalized.document_type,
            normalized.source_path_contains,
            normalized.ids,
            normalized.quality_flags,
        ]
    ):
        raise ValueError("Bulk reprocess requires at least one selector")
    return normalized


def bulk_reprocess_documents(
    db: Session,
    *,
    filters: BulkReprocessFilters,
    user: User,
    enqueue: bool = True,
) -> BulkReprocessResult:
    normalized = normalize_bulk_reprocess_filters(filters)
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(Document.status != "duplicate")
        .order_by(Document.created_at.desc())
        .limit(normalized.limit)
    )
    if normalized.ids:
        stmt = stmt.where(Document.id.in_(normalized.ids))
    if normalized.status:
        stmt = stmt.where(Document.status == normalized.status)
    if normalized.document_type:
        stmt = stmt.where(Document.document_type == normalized.document_type)
    if normalized.source_path_contains:
        stmt = stmt.where(Document.source_path.ilike(f"%{normalized.source_path_contains}%"))
    if normalized.quality_flags:
        for flag in normalized.quality_flags:
            stmt = stmt.where(
                text("quality_flags_json::jsonb ? :flag")
            ).params(flag=flag)

    documents = list(db.scalars(stmt).all())
    job_ids: list[int] = []
    skipped = 0
    active_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
        or 0
    )
    active_doc_ids = {
        row[0]
        for row in db.execute(
            select(ExtractionJob.document_id)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
            .distinct()
        )
    }
    for document in documents:
        if active_jobs >= settings.ingestion_max_pending_jobs:
            skipped += len(documents) - len(job_ids) - skipped
            break
        if document.id in active_doc_ids:
            skipped += 1
            continue
        job = reprocess_document(
            db,
            document=document,
            user=user,
            enqueue=enqueue,
            job_type=f"reprocess:{normalized.mode}",
        )
        job_ids.append(job.id)
        active_jobs += 1

    write_audit(
        db,
        user=user,
        action="documents_bulk_reprocess_requested",
        entity_type="document",
        details={
            "matched": len(documents),
            "enqueued": len(job_ids),
            "mode": normalized.mode,
            "filters": {
                "status": normalized.status,
                "document_type": normalized.document_type,
                "source_path_contains": normalized.source_path_contains,
                "ids": normalized.ids,
                "limit": normalized.limit,
            },
        },
    )
    db.commit()
    return BulkReprocessResult(
        matched=len(documents),
        enqueued=len(job_ids),
        skipped=skipped,
        job_ids=job_ids,
        mode=normalized.mode,
    )


def build_admin_alerts(db: Session) -> list[AdminAlert]:
    counts = {
        "accepted_budgets_without_order": _count_accepted_budgets_without_order(db),
        "orders_without_budget": int(
            db.scalar(
                select(func.count()).select_from(Order).where(Order.related_budget_id.is_(None))
            )
            or 0
        ),
        "ocr_review_documents": int(
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.deleted_at.is_(None))
                .where(Document.status.in_(["failed", "needs_review"]))
            )
            or 0
        ),
        "plans_without_valid_scale": int(
            db.scalar(select(func.count()).select_from(Plan).where(Plan.has_valid_scale.is_(False)))
            or 0
        ),
        "duplicate_documents": int(
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.deleted_at.is_(None))
                .where(Document.status == "duplicate")
            )
            or 0
        ),
        "failed_jobs": int(
            db.scalar(
                select(func.count())
                .select_from(ExtractionJob)
                .where(ExtractionJob.status == "failed")
            )
            or 0
        ),
        "low_quality_documents": int(
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.deleted_at.is_(None))
                .where(
                    Document.quality_status.in_(
                        ["processed_low_quality", "processed_missing_fields", "needs_human_review"]
                    )
                )
            )
            or 0
        ),
        "disk_low": _disk_low_count(),
        "queue_backpressure": _queue_backpressure_count(db),
    }
    alerts: list[AdminAlert] = []
    for definition in ALERT_DEFINITIONS:
        count = counts.get(definition.key, 0)
        if count <= 0:
            continue
        alerts.append(
            AdminAlert(
                key=definition.key,
                title=definition.title,
                description=definition.description,
                severity=definition.severity,
                count=count,
                action_url=definition.action_url,
            )
        )
    return alerts


def build_processing_metrics(db: Session) -> dict:
    return {
        "documents_by_status": _group_count(
            db, Document.status, Document, Document.deleted_at.is_(None)
        ),
        "documents_by_type": _group_count(
            db, Document.document_type, Document, Document.deleted_at.is_(None)
        ),
        "jobs_by_status": _group_count(db, ExtractionJob.status, ExtractionJob),
        "audit_events_total": int(db.scalar(select(func.count()).select_from(AuditLog)) or 0),
    }


def _count_accepted_budgets_without_order(db: Session) -> int:
    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    return int(
        db.scalar(
            select(func.count())
            .select_from(Budget)
            .where(Budget.accepted_detected.is_(True))
            .where(Budget.id.not_in(ordered_budget_ids))
        )
        or 0
    )


def _group_count(db: Session, column, model, *criteria) -> dict[str, int]:
    stmt = select(column, func.count()).select_from(model)
    if criteria:
        stmt = stmt.where(*criteria)
    stmt = stmt.group_by(column)
    return {str(key or "unknown"): int(count) for key, count in db.execute(stmt).all()}


def _queue_backpressure_count(db: Session) -> int:
    active = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
        or 0
    )
    return 1 if active >= settings.ingestion_max_pending_jobs else 0


def _disk_low_count() -> int:
    low = 0
    for path in (settings.files_dir, settings.input_dir):
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            usage = shutil.disk_usage(probe)
        except OSError:
            continue
        if usage.total and usage.free / usage.total < 0.10:
            low += 1
    return low


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
