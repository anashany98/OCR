from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import ExtractionJob, User
from app.schemas.jobs import ExtractionJobRead
from app.services.tenant_access import filter_document_ids_for_scope, resolve_user_access_scope

router = APIRouter()


@router.get("", response_model=list[ExtractionJobRead])
def list_jobs(
    status: str | None = None,
    document_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ExtractionJob]:
    stmt = select(ExtractionJob).order_by(ExtractionJob.id.desc())
    if status:
        stmt = stmt.where(ExtractionJob.status == status)
    if document_id:
        stmt = stmt.where(ExtractionJob.document_id == document_id)
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.offset(offset).limit(limit)).all())
    candidates = list(db.scalars(stmt.limit(max(limit + offset, 500))).all())
    allowed = filter_document_ids_for_scope(db, [job.document_id for job in candidates], scope)
    return [job for job in candidates if job.document_id in allowed][offset : offset + limit]


@router.get("/{job_id}", response_model=ExtractionJobRead)
def get_job(
    job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ExtractionJob:
    job = db.get(ExtractionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    allowed = filter_document_ids_for_scope(
        db, [job.document_id], resolve_user_access_scope(db, user)
    )
    if job.document_id not in allowed:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
