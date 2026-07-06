"""Admin dashboard endpoint.

Provides a structured JSON response with aggregated metrics
for the frontend dashboard. Unlike the raw Prometheus metrics,
this endpoint returns pre-formatted data ready for charts and
status indicators.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import (
    AIAnswer,
    AIQuestion,
    Document,
    DocumentPage,
    ExtractionJob,
    User,
)

router = APIRouter(tags=["admin"])


@router.get("/admin/dashboard")
def dashboard_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """Aggregated dashboard metrics for the admin overview."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    # ── Document stats ──────────────────────────────────────────
    total_docs = db.scalar(select(func.count(Document.id)).where(Document.deleted_at.is_(None))) or 0
    docs_today = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.deleted_at.is_(None),
                Document.created_at >= today_start,
            )
        )
        or 0
    )
    docs_this_week = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.deleted_at.is_(None),
                Document.created_at >= week_start,
            )
        )
        or 0
    )

    # Status breakdown
    status_rows = (
        db.execute(
            select(Document.status, func.count(Document.id)).where(
                Document.deleted_at.is_(None)
            ).group_by(Document.status)
        ).all()
    )
    docs_by_status = {row[0]: row[1] for row in status_rows}

    # Document types breakdown
    type_rows = (
        db.execute(
            select(Document.document_type, func.count(Document.id)).where(
                Document.deleted_at.is_(None)
            ).group_by(Document.document_type)
        ).all()
    )
    docs_by_type = {row[0]: row[1] for row in type_rows}

    # Average OCR confidence
    avg_confidence = (
        db.scalar(
            select(func.avg(DocumentPage.ocr_confidence)).where(
                DocumentPage.ocr_confidence.is_not(None)
            )
        )
        or 0.0
    )

    # ── Processing stats ────────────────────────────────────────
    total_jobs = db.scalar(select(func.count(ExtractionJob.id))) or 0
    jobs_processing = (
        db.scalar(
            select(func.count(ExtractionJob.id)).where(ExtractionJob.status == "processing")
        )
        or 0
    )
    jobs_failed_today = (
        db.scalar(
            select(func.count(ExtractionJob.id)).where(
                ExtractionJob.status == "failed",
                ExtractionJob.finished_at >= today_start,
            )
        )
        or 0
    )

    # Processing time (average of finished jobs today)
    avg_processing_time = (
        db.scalar(
            select(
                func.avg(
                    func.extract("epoch", ExtractionJob.finished_at)
                    - func.extract("epoch", ExtractionJob.started_at)
                )
            ).where(
                ExtractionJob.status == "processed",
                ExtractionJob.finished_at >= today_start,
                ExtractionJob.started_at.is_not(None),
                ExtractionJob.finished_at.is_not(None),
            )
        )
        or 0.0
    )

    # ── AI / Chat stats ─────────────────────────────────────────
    total_questions = db.scalar(select(func.count(AIQuestion.id))) or 0
    questions_today = (
        db.scalar(
            select(func.count(AIQuestion.id)).where(AIQuestion.created_at >= today_start)
        )
        or 0
    )
    total_answers = db.scalar(select(func.count(AIAnswer.id))) or 0

    # Average AI confidence
    avg_ai_confidence = (
        db.scalar(select(func.avg(AIAnswer.confidence)).where(AIAnswer.confidence.is_not(None)))
        or 0.0
    )

    # ── User stats ──────────────────────────────────────────────
    total_users = db.scalar(select(func.count(User.id))) or 0
    active_users_today = (
        db.scalar(
            select(func.count(func.distinct(AIQuestion.user_id))).where(
                AIQuestion.created_at >= today_start
            )
        )
        or 0
    )

    # ── Storage ─────────────────────────────────────────────────
    total_file_size = (
        db.scalar(
            select(func.sum(Document.file_size)).where(Document.deleted_at.is_(None))
        )
        or 0
    )

    return {
        "timestamp": now.isoformat(),
        "documents": {
            "total": total_docs,
            "today": docs_today,
            "this_week": docs_this_week,
            "by_status": docs_by_status,
            "by_type": docs_by_type,
            "avg_ocr_confidence": round(float(avg_confidence), 3),
            "total_size_bytes": total_file_size,
        },
        "processing": {
            "total_jobs": total_jobs,
            "currently_processing": jobs_processing,
            "failed_today": jobs_failed_today,
            "avg_processing_time_seconds": round(float(avg_processing_time), 2),
        },
        "ai": {
            "total_questions": total_questions,
            "questions_today": questions_today,
            "total_answers": total_answers,
            "avg_confidence": round(float(avg_ai_confidence), 3),
        },
        "users": {
            "total": total_users,
            "active_today": active_users_today,
        },
    }


@router.get("/admin/dashboard/activity")
def dashboard_activity(
    days: int = 7,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """Daily activity breakdown for the last N days."""
    now = datetime.now(UTC)
    start_date = now - timedelta(days=days)

    # Documents per day
    docs_per_day = (
        db.execute(
            select(
                func.date(Document.created_at).label("day"),
                func.count(Document.id),
            )
            .where(Document.created_at >= start_date)
            .group_by(func.date(Document.created_at))
            .order_by(func.date(Document.created_at))
        ).all()
    )

    # Questions per day
    questions_per_day = (
        db.execute(
            select(
                func.date(AIQuestion.created_at).label("day"),
                func.count(AIQuestion.id),
            )
            .where(AIQuestion.created_at >= start_date)
            .group_by(func.date(AIQuestion.created_at))
            .order_by(func.date(AIQuestion.created_at))
        ).all()
    )

    # Jobs per day
    jobs_per_day = (
        db.execute(
            select(
                func.date(ExtractionJob.finished_at).label("day"),
                func.count(ExtractionJob.id),
            )
            .where(
                ExtractionJob.finished_at >= start_date,
                ExtractionJob.status == "processed",
            )
            .group_by(func.date(ExtractionJob.finished_at))
            .order_by(func.date(ExtractionJob.finished_at))
        ).all()
    )

    # OCR confidence trend (average per day)
    confidence_trend = (
        db.execute(
            select(
                func.date(DocumentPage.created_at).label("day"),
                func.avg(DocumentPage.ocr_confidence),
            )
            .where(
                DocumentPage.created_at >= start_date,
                DocumentPage.ocr_confidence.is_not(None),
            )
            .group_by(func.date(DocumentPage.created_at))
            .order_by(func.date(DocumentPage.created_at))
        ).all()
    )

    # Failed jobs per day
    failed_per_day = (
        db.execute(
            select(
                func.date(ExtractionJob.finished_at).label("day"),
                func.count(ExtractionJob.id),
            )
            .where(
                ExtractionJob.finished_at >= start_date,
                ExtractionJob.status == "failed",
            )
            .group_by(func.date(ExtractionJob.finished_at))
            .order_by(func.date(ExtractionJob.finished_at))
        ).all()
    )

    return {
        "period_days": days,
        "documents_per_day": [
            {"date": str(row[0]), "count": row[1]} for row in docs_per_day
        ],
        "questions_per_day": [
            {"date": str(row[0]), "count": row[1]} for row in questions_per_day
        ],
        "jobs_per_day": [
            {"date": str(row[0]), "count": row[1]} for row in jobs_per_day
        ],
        "failed_per_day": [
            {"date": str(row[0]), "count": row[1]} for row in failed_per_day
        ],
        "confidence_trend": [
            {"date": str(row[0]), "confidence": round(float(row[1]), 3)}
            for row in confidence_trend
            if row[1] is not None
        ],
    }


@router.get("/admin/dashboard/workers")
def dashboard_workers(
    _: User = Depends(require_roles("admin")),
) -> dict:
    """Worker status from Celery inspect."""
    try:
        from app.workers.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=3.0)
        active = inspect.active() or {}
        stats = inspect.stats() or {}

        workers = []
        for worker_name, worker_stats in stats.items():
            pool = worker_stats.get("pool", {})
            workers.append({
                "name": worker_name,
                "status": "online",
                "pid": worker_stats.get("pid"),
                "pool_processes": pool.get("max-concurrency"),
                "active_tasks": len(active.get(worker_name, [])),
                "cpu_usage": worker_stats.get("rusage", {}),
            })

        return {"workers": workers, "total": len(workers)}
    except Exception:
        return {"workers": [], "total": 0, "error": "Celery inspect failed"}
