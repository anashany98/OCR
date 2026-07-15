from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.routes.admin_helpers import (
    _document_operation_payload,
    _ingestion_event_payload,
    _severity_rank,
    _watched_file_payload,
)
from app.core.config import settings
from app.database.session import get_db
from app.models import (
    Budget,
    Document,
    DocumentChunk,
    DocumentPage,
    ExtractionJob,
    IngestionEvent,
    Order,
    User,
    WatchedFile,
)
from app.schemas.admin import (
    NeedsReembeddingItem,
    PaginatedDocumentsResponse,
    QueueStatusRead,
    StorageIntegrityResponse,
    WorkInboxActionRequest,
    WorkInboxActionResponse,
    WorkInboxCountRead,
    WorkInboxItemRead,
)
from app.services.audit import write_audit
from app.services.document_service import reprocess_document
from app.services.maintenance import build_operations_overview, build_operations_status
from app.services.ocr_page_roles import ocr_applicable_clause
from app.services.production_readiness import storage_integrity
from app.services.queue_control import (
    build_queue_control_status,
    pause_ingestion,
    resume_ingestion,
)
from app.services.tenant_access import (
    AccessScope,
    apply_access_predicates,
    can_access_document,
    filter_document_ids_for_scope,
    filter_documents_for_scope,
    filter_records_by_document_scope,
    resolve_user_access_scope,
)

router = APIRouter(prefix="/admin")


@router.get("/operations-status")
def operations_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_operations_status(db)


@router.get("/operations/overview")
def operations_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return build_operations_overview(db)


@router.get("/operations/documents", response_model=PaginatedDocumentsResponse)
def operations_documents(
    status: str | None = None,
    document_type: str | None = None,
    q: str | None = None,
    quality_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    scope = resolve_user_access_scope(db, user)
    stmt = select(Document).where(Document.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
    criteria = []
    if status:
        criteria.append(Document.status == status)
    if document_type:
        criteria.append(Document.document_type == document_type)
    if quality_status:
        criteria.append(Document.quality_status == quality_status)
    if q:
        criteria.append(Document.original_filename.ilike(f"%{q}%"))
    if criteria:
        stmt = stmt.where(*criteria)
        count_stmt = count_stmt.where(*criteria)
    stmt = stmt.order_by(Document.created_at.desc())
    if scope.is_admin:
        documents = list(db.scalars(stmt.offset(offset).limit(limit)).all())
        total = int(db.scalar(count_stmt) or 0)
    else:
        # DATA-03: same fix as the public documents endpoint. We
        # push the location scope into SQL so the offset/limit
        # window is computed over the filtered set, not over a
        # 1000-row candidate cap.
        stmt = apply_access_predicates(stmt, scope)
        count_stmt = apply_access_predicates(count_stmt, scope)
        documents = list(db.scalars(stmt.offset(offset).limit(limit)).all())
        # The in-memory helper still drops rows that fail the
        # ``denied_tags`` / ``allowed_document_types`` checks. The
        # page may end up shorter than ``limit`` in that case,
        # which is the documented trade-off documented for
        # ``list_documents``.
        documents = filter_documents_for_scope(db, documents, scope)
        total = int(db.scalar(count_stmt) or 0)
    return {
        "items": [_document_operation_payload(document) for document in documents],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/queues", response_model=QueueStatusRead)
def queues(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> QueueStatusRead:
    return QueueStatusRead(**build_queue_control_status(db).__dict__)


@router.post("/queues/pause", response_model=QueueStatusRead)
def pause_queues(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> QueueStatusRead:
    pause_ingestion()
    write_audit(db, user=user, action="ingestion_paused", entity_type="operations")
    db.commit()
    return QueueStatusRead(**build_queue_control_status(db).__dict__)


@router.post("/queues/resume", response_model=QueueStatusRead)
def resume_queues(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> QueueStatusRead:
    resume_ingestion()
    write_audit(db, user=user, action="ingestion_resumed", entity_type="operations")
    db.commit()
    return QueueStatusRead(**build_queue_control_status(db).__dict__)


@router.get("/storage/integrity", response_model=StorageIntegrityResponse)
def storage_integrity_endpoint(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    return storage_integrity(db, limit=limit)


@router.get("/watched-files")
def watched_files(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[dict]:
    stmt = select(WatchedFile).order_by(WatchedFile.updated_at.desc())
    if status_filter:
        stmt = stmt.where(WatchedFile.status == status_filter)
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        rows = list(db.scalars(stmt.limit(limit)).all())
    else:
        # Pull a candidate set and filter by accessible documents.
        # WatchedFile rows that have not yet been linked to a
        # document (still being scanned / failing) are not filtered
        # — they are operational metadata with no business content
        # — but the filesystem path itself is redacted by
        # ``_watched_file_payload`` for non-admin scopes.
        candidates = list(db.scalars(stmt.limit(max(limit * 5, 500))).all())
        document_ids = {row.document_id for row in candidates if row.document_id is not None}
        allowed = filter_document_ids_for_scope(db, document_ids, scope)
        rows = [row for row in candidates if row.document_id is None or row.document_id in allowed][
            :limit
        ]
    return [_watched_file_payload(row, scope) for row in rows]


@router.get("/ingestion-events")
def ingestion_events(
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[dict]:
    stmt = select(IngestionEvent).order_by(IngestionEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(IngestionEvent.event_type == event_type)
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        rows = list(db.scalars(stmt.limit(limit)).all())
    else:
        # Same model as ``watched_files``: filter by accessible
        # documents, keep unlinked events, redact filesystem paths.
        candidates = list(db.scalars(stmt.limit(max(limit * 5, 500))).all())
        document_ids = {row.document_id for row in candidates if row.document_id is not None}
        allowed = filter_document_ids_for_scope(db, document_ids, scope)
        rows = [row for row in candidates if row.document_id is None or row.document_id in allowed][
            :limit
        ]
    return [_ingestion_event_payload(row, scope) for row in rows]


@router.get("/work-inbox", response_model=list[WorkInboxItemRead])
def work_inbox(
    max_ocr_confidence: float = Query(default=settings.low_ocr_confidence_threshold, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[WorkInboxItemRead]:
    scope = resolve_user_access_scope(db, user)
    candidate_limit = limit if scope.is_admin else max(limit * 5, 500)
    items: list[WorkInboxItemRead] = []

    low_ocr_rows = db.execute(
        select(DocumentPage, Document)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(ocr_applicable_clause(DocumentPage.ocr_content_kind))
        .where(DocumentPage.ocr_confidence.is_not(None))
        .where(DocumentPage.ocr_confidence < max_ocr_confidence)
        .where(DocumentPage.review_status != "approved")
        .order_by(DocumentPage.ocr_confidence.asc(), Document.created_at.desc())
        .limit(candidate_limit)
    ).all()
    low_ocr_rows = _filter_document_rows_for_scope(db, low_ocr_rows, scope, document_index=1)[
        :limit
    ]
    for page, document in low_ocr_rows:
        items.append(
            WorkInboxItemRead(
                kind="low_ocr",
                severity="warning",
                title="OCR de baja confianza",
                description=f"{document.original_filename}, pagina {page.page_number}: {page.ocr_confidence or 0:.0%}",
                document_id=document.id,
                page_id=page.id,
                action_url=f"/ocr-review?document={document.id}&page={page.id}",
                status=page.review_status,
                created_at=page.created_at,
            )
        )

    unknown_documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.document_type == "desconocido")
            .order_by(Document.created_at.desc())
            .limit(candidate_limit)
        ).all()
    )
    for document in filter_documents_for_scope(db, unknown_documents, scope)[:limit]:
        items.append(
            WorkInboxItemRead(
                kind="unknown_type",
                severity="warning",
                title="Documento sin clasificar",
                description=document.original_filename,
                document_id=document.id,
                action_url=f"/documents/{document.id}",
                status=document.status,
                created_at=document.created_at,
            )
        )

    duplicate_documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "duplicate")
            .order_by(Document.created_at.desc())
            .limit(candidate_limit)
        ).all()
    )
    for document in filter_documents_for_scope(db, duplicate_documents, scope)[:limit]:
        items.append(
            WorkInboxItemRead(
                kind="duplicate",
                severity="info",
                title="Documento duplicado",
                description=document.original_filename,
                document_id=document.id,
                action_url=f"/documents/{document.id}",
                status=document.status,
                created_at=document.created_at,
            )
        )

    failed_jobs = db.execute(
        select(ExtractionJob, Document)
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(Document.deleted_at.is_(None))
        .where(ExtractionJob.status == "failed")
        .order_by(ExtractionJob.finished_at.desc().nullslast(), Document.created_at.desc())
        .limit(candidate_limit)
    ).all()
    failed_jobs = _filter_document_rows_for_scope(db, failed_jobs, scope, document_index=1)[:limit]
    for job, document in failed_jobs:
        items.append(
            WorkInboxItemRead(
                kind="failed_job",
                severity="error",
                title="Job fallido",
                description=job.error_message or document.original_filename,
                document_id=document.id,
                job_id=job.id,
                action_url=f"/jobs?job={job.id}",
                status=job.status,
                created_at=job.finished_at or document.created_at,
            )
        )

    review_documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(
                Document.quality_status.in_(
                    ["processed_missing_fields", "needs_human_review", "processed_low_quality"]
                )
            )
            .order_by(Document.created_at.desc())
            .limit(candidate_limit)
        ).all()
    )
    for document in filter_documents_for_scope(db, review_documents, scope)[:limit]:
        items.append(
            WorkInboxItemRead(
                kind="missing_fields"
                if document.quality_status == "processed_missing_fields"
                else document.quality_status,
                severity="warning",
                title="Documento requiere revision",
                description=f"{document.original_filename}: {document.quality_status}",
                document_id=document.id,
                action_url=f"/documents/{document.id}",
                status=document.status,
                created_at=document.created_at,
            )
        )

    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    accepted_budgets = db.scalars(
        select(Budget)
        .join(Document, Document.id == Budget.document_id)
        .where(Document.deleted_at.is_(None))
        .where(
            or_(
                Budget.accepted_detected.is_(True),
                Budget.status.in_(["aceptado", "aprobado", "accepted"]),
            )
        )
        .where(Budget.id.not_in(ordered_budget_ids))
        .order_by(Budget.created_at.desc())
        .limit(candidate_limit)
    ).all()
    accepted_budgets = filter_records_by_document_scope(db, accepted_budgets, scope)[:limit]
    for budget in accepted_budgets:
        items.append(
            WorkInboxItemRead(
                kind="accepted_budget_without_order",
                severity="warning",
                title="Presupuesto aceptado sin pedido",
                description=budget.budget_number or f"Presupuesto #{budget.id}",
                document_id=budget.document_id,
                action_url=f"/budgets/{budget.id}",
                status=budget.status,
                created_at=budget.created_at,
            )
        )

    items.sort(
        key=lambda item: (_severity_rank(item.severity), item.created_at or datetime.min),
        reverse=True,
    )
    return items[:limit]


def _work_inbox_counts(
    db: Session,
    *,
    max_ocr_confidence: float,
    scope: AccessScope | None = None,
) -> dict[str, int]:
    scope = scope or AccessScope(principal_type="system", principal_id="system", is_admin=True)
    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    low_ocr_rows = db.execute(
        select(DocumentPage.id, Document.id)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(ocr_applicable_clause(DocumentPage.ocr_content_kind))
        .where(DocumentPage.ocr_confidence.is_not(None))
        .where(DocumentPage.ocr_confidence < max_ocr_confidence)
        .where(DocumentPage.review_status != "approved")
    ).all()
    failed_job_rows = db.execute(
        select(ExtractionJob.id, Document.id)
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(Document.deleted_at.is_(None))
        .where(ExtractionJob.status == "failed")
    ).all()
    accepted_budgets = list(
        db.scalars(
            select(Budget)
            .join(Document, Document.id == Budget.document_id)
            .where(Document.deleted_at.is_(None))
            .where(
                or_(
                    Budget.accepted_detected.is_(True),
                    Budget.status.in_(["aceptado", "aprobado", "accepted"]),
                )
            )
            .where(Budget.id.not_in(ordered_budget_ids))
        ).all()
    )
    counts = {
        "low_ocr": _count_rows_allowed_by_document(db, low_ocr_rows, scope, document_index=1),
        "unknown_type": _count_documents_allowed_by_scope(
            db,
            select(Document.id)
            .where(Document.deleted_at.is_(None))
            .where(Document.document_type == "desconocido"),
            scope,
        ),
        "duplicate": _count_documents_allowed_by_scope(
            db,
            select(Document.id)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "duplicate"),
            scope,
        ),
        "failed_job": _count_rows_allowed_by_document(db, failed_job_rows, scope, document_index=1),
        "quality_review": _count_documents_allowed_by_scope(
            db,
            select(Document.id)
            .where(Document.deleted_at.is_(None))
            .where(
                Document.quality_status.in_(
                    ["processed_missing_fields", "needs_human_review", "processed_low_quality"]
                )
            ),
            scope,
        ),
        "accepted_budget_without_order": len(
            filter_records_by_document_scope(db, accepted_budgets, scope)
        ),
    }
    return counts


@router.get("/work-inbox/count", response_model=WorkInboxCountRead)
def work_inbox_count(
    max_ocr_confidence: float = Query(default=settings.low_ocr_confidence_threshold, ge=0, le=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> WorkInboxCountRead:
    by_kind = _work_inbox_counts(
        db, max_ocr_confidence=max_ocr_confidence, scope=resolve_user_access_scope(db, user)
    )
    return WorkInboxCountRead(count=sum(by_kind.values()), by_kind=by_kind)


@router.post("/work-inbox/actions", response_model=WorkInboxActionResponse)
def work_inbox_action(
    payload: WorkInboxActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> WorkInboxActionResponse:
    scope = resolve_user_access_scope(db, user)
    candidate_limit = payload.limit if scope.is_admin else max(payload.limit * 5, 500)
    job_ids: list[int] = []
    matched = 0
    updated = 0
    enqueued = 0

    if payload.action == "retry_failed_jobs":
        jobs = list(
            db.scalars(
                select(ExtractionJob)
                .where(ExtractionJob.status == "failed")
                .order_by(ExtractionJob.finished_at.desc().nullslast(), ExtractionJob.id.desc())
                .limit(candidate_limit)
            ).all()
        )
        jobs = _filter_records_by_document_id(db, jobs, scope)[: payload.limit]
        matched = len(jobs)
        for job in jobs:
            document = db.get(Document, job.document_id)
            if not document or document.deleted_at is not None:
                continue
            new_job = reprocess_document(
                db,
                document=document,
                user=user,
                job_type=job.job_type or "extract",
                enqueue=not settings.database_url.startswith("sqlite"),
            )
            job_ids.append(new_job.id)
            enqueued += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_retry_failed_jobs",
            entity_type="operations",
            details={"matched": matched, "enqueued": enqueued, "job_ids": job_ids},
        )
        db.commit()
    elif payload.action == "approve_high_confidence_ocr":
        pages = list(
            db.scalars(
                select(DocumentPage)
                .join(Document, Document.id == DocumentPage.document_id)
                .where(Document.deleted_at.is_(None))
                .where(Document.status == "processed")
                .where(ocr_applicable_clause(DocumentPage.ocr_content_kind))
                .where(DocumentPage.ocr_confidence.is_not(None))
                .where(DocumentPage.ocr_confidence >= payload.min_confidence)
                .where(DocumentPage.review_status != "approved")
                .order_by(DocumentPage.ocr_confidence.desc())
                .limit(candidate_limit)
            ).all()
        )
        pages = _filter_records_by_document_id(db, pages, scope)[: payload.limit]
        matched = len(pages)
        for page in pages:
            page.review_status = "approved"
            page.review_notes = "Aprobado por accion en lote."
            page.reviewed_at = datetime.now(UTC)
            page.reviewed_by_id = user.id
            updated += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_approve_high_confidence_ocr",
            entity_type="document_page",
            details={
                "matched": matched,
                "updated": updated,
                "min_confidence": payload.min_confidence,
            },
        )
        db.commit()
    elif payload.action == "reprocess_low_quality":
        documents = list(
            db.scalars(
                select(Document)
                .where(Document.deleted_at.is_(None))
                .where(Document.quality_status.in_(["processed_low_quality", "needs_human_review"]))
                .order_by(Document.created_at.desc())
                .limit(candidate_limit)
            ).all()
        )
        documents = filter_documents_for_scope(db, documents, scope)[: payload.limit]
        matched = len(documents)
        for document in documents:
            new_job = reprocess_document(
                db,
                document=document,
                user=user,
                job_type="reprocess:ocr",
                enqueue=not settings.database_url.startswith("sqlite"),
            )
            job_ids.append(new_job.id)
            enqueued += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_reprocess_low_quality",
            entity_type="operations",
            details={"matched": matched, "enqueued": enqueued, "job_ids": job_ids},
        )
        db.commit()
    elif payload.action == "mark_duplicates_reviewed":
        documents = list(
            db.scalars(
                select(Document)
                .where(Document.deleted_at.is_(None))
                .where(Document.status == "duplicate")
                .order_by(Document.created_at.desc())
                .limit(candidate_limit)
            ).all()
        )
        documents = filter_documents_for_scope(db, documents, scope)[: payload.limit]
        matched = len(documents)
        for document in documents:
            document.quality_status = "processed_ok"
            updated += 1
        write_audit(
            db,
            user=user,
            action="work_inbox_mark_duplicates_reviewed",
            entity_type="document",
            details={"matched": matched, "updated": updated},
        )
        db.commit()

    return WorkInboxActionResponse(
        action=payload.action,
        matched=matched,
        updated=updated,
        enqueued=enqueued,
        job_ids=job_ids,
    )


@router.post("/documents/{document_id}/re-embed")
def reembed_document_endpoint(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    """Re-run the embedding step for an existing document.

    Re-uses the page texts already stored in ``DocumentPage.text`` so we
    don't re-OCR. Useful when the original embedding failed (provider
    was down, model couldn't load on a CPU worker, etc.) and the
    document is sitting in the queue with ``needs_reembedding=True``
    on every chunk.

    Never raises on embedding failure: chunks that still can't be
    embedded keep ``needs_reembedding=True`` so the admin can try
    again. This matches the "no silent hash fallback" policy.
    """
    from app.services.document_embedding_pipeline import reembed_document

    # SEC-ADMIN-1: a gestor/auditor must not be able to re-embed a
    # document they cannot otherwise access. Refuse the call early so
    # we never touch ``DocumentPage.text`` or schedule work on an
    # out-of-scope document.
    scope = resolve_user_access_scope(db, user)
    document = db.get(Document, document_id)
    if not document or not can_access_document(db, document, scope):
        raise HTTPException(status_code=404, detail="Document not found")

    result = reembed_document(db, document_id)
    write_audit(
        db,
        user=user,
        action="document_reembed",
        entity_type="document",
        entity_id=document_id,
        details={
            "chunks_updated": result["chunks_updated"],
            "chunks_with_embedding": result["chunks_with_embedding"],
            "chunks_needing_reembedding": result["chunks_needing_reembedding"],
            "provider": result["provider"],
        },
    )
    db.commit()
    return result


@router.get("/documents/needs-re-embedding", response_model=list[NeedsReembeddingItem])
def list_documents_needing_reembedding(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[NeedsReembeddingItem]:
    """List documents with at least one chunk where ``needs_reembedding=True``.

    One row per document, with the total chunk count and the count of
    chunks that still need an embedding. Ordered by document creation
    date (newest first) so freshly-failed uploads surface at the top of
    the list.
    """
    # Conditional aggregation: count total chunks and chunks needing
    # re-embedding per document. We only emit a row for documents that
    # have at least one chunk needing re-embedding.
    needs_case = case((DocumentChunk.needs_reembedding.is_(True), 1), else_=0)
    stats_subq = (
        select(
            DocumentChunk.document_id.label("document_id"),
            func.count(DocumentChunk.id).label("chunks_total"),
            func.coalesce(func.sum(needs_case), 0).label("chunks_needing"),
        )
        .group_by(DocumentChunk.document_id)
        .having(func.sum(needs_case) > 0)
        .subquery()
    )
    stmt = (
        select(Document, stats_subq.c.chunks_total, stats_subq.c.chunks_needing)
        .join(stats_subq, Document.id == stats_subq.c.document_id)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        rows = db.execute(stmt.limit(limit)).all()
    else:
        # SEC-ADMIN-1: scope the result to documents the caller can
        # access. The aggregation itself stays in SQL; we just pull a
        # larger candidate window and filter the joined rows by
        # ``document_id``.
        candidates = db.execute(stmt.limit(max(limit * 5, 500))).all()
        documents = [row[0] for row in candidates]
        allowed = set(
            filter_document_ids_for_scope(
                db,
                [document.id for document in documents],
                scope,
            )
        )
        rows = [row for row in candidates if row[0].id in allowed][:limit]

    return [
        NeedsReembeddingItem(
            document_id=document.id,
            original_filename=document.original_filename,
            document_type=document.document_type,
            status=document.status,
            created_at=document.created_at,
            chunks_total=int(chunks_total),
            chunks_needing_reembedding=int(chunks_needing),
        )
        for document, chunks_total, chunks_needing in rows
    ]


def _filter_document_rows_for_scope(
    db: Session,
    rows: list,
    scope: AccessScope,
    *,
    document_index: int,
) -> list:
    if scope.is_admin:
        return rows
    allowed_document_ids = filter_document_ids_for_scope(
        db, [row[document_index].id for row in rows], scope
    )
    return [row for row in rows if row[document_index].id in allowed_document_ids]


def _filter_records_by_document_id(db: Session, records: list, scope: AccessScope) -> list:
    if scope.is_admin:
        return records
    allowed_document_ids = filter_document_ids_for_scope(
        db, [record.document_id for record in records], scope
    )
    return [record for record in records if record.document_id in allowed_document_ids]


def _count_rows_allowed_by_document(
    db: Session,
    rows: list,
    scope: AccessScope,
    *,
    document_index: int,
) -> int:
    if scope.is_admin:
        return len(rows)
    allowed_document_ids = filter_document_ids_for_scope(
        db, [row[document_index] for row in rows], scope
    )
    return sum(1 for row in rows if row[document_index] in allowed_document_ids)


def _count_documents_allowed_by_scope(db: Session, document_id_stmt, scope: AccessScope) -> int:
    document_ids = list(db.scalars(document_id_stmt).all())
    if scope.is_admin:
        return len(document_ids)
    return len(filter_document_ids_for_scope(db, document_ids, scope))
