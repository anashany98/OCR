import csv
import io
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import AuditLog, Document, ExtractionJob, User
from app.schemas.admin import AuditLogRead, JobActionResponse
from app.services.audit import write_audit
from app.services.document_service import reprocess_document
from app.services.queue_control import cancel_pending_job

from app.api.routes.admin_helpers import _get_or_404

router = APIRouter(prefix="/admin")


@router.post("/jobs/{job_id}/retry", response_model=JobActionResponse)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ExtractionJob:
    job = _get_or_404(db, ExtractionJob, job_id, "Job not found")
    document = _get_or_404(db, Document, job.document_id, "Document not found")
    new_job = reprocess_document(db, document=document, user=user, job_type=job.job_type)
    write_audit(
        db,
        user=user,
        action="job_retry_requested",
        entity_type="extraction_job",
        entity_id=job.id,
        details={"new_job_id": new_job.id, "document_id": document.id},
    )
    db.commit()
    db.refresh(new_job)
    return new_job


@router.post("/jobs/{job_id}/cancel", response_model=JobActionResponse)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ExtractionJob:
    job = _get_or_404(db, ExtractionJob, job_id, "Job not found")
    try:
        cancel_pending_job(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(db, user=user, action="job_cancelled", entity_type="extraction_job", entity_id=job.id)
    db.commit()
    db.refresh(job)
    return job


@router.get("/audit-logs", response_model=list[AuditLogRead])
def audit_logs(
    action: str | None = None,
    entity_type: str | None = None,
    user_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return list(db.scalars(stmt.offset(offset).limit(limit)).all())


@router.get("/audit-logs/export/json")
def audit_logs_export_json(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    payload = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "details_json": row.details_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return StreamingResponse(
        iter([json.dumps(payload, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=docuintel_audit_logs.json"},
    )


@router.get("/audit-logs/export/csv")
def audit_logs_export_csv(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "user_id", "action", "entity_type", "entity_id", "details_json"])
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat() if row.created_at else "",
                row.user_id or "",
                row.action,
                row.entity_type or "",
                row.entity_id or "",
                json.dumps(row.details_json or {}, ensure_ascii=False),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=docuintel_audit_logs.csv"},
    )
