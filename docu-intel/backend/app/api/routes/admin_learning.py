from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import ClassificationSuggestion, LearnedPattern, User
from app.schemas.learning import ClassificationSuggestionRead, LearnedPatternRead
from app.services.audit import write_audit
from app.services.learning_health import health_snapshot
from app.services.webhooks import emit_new_pattern_detected

logger = logging.getLogger(__name__)
router = APIRouter()


VALID_SUGGESTION_TYPES = Literal[
    "classification_correction", "entity_link", "classification_rule", "quality_feedback"
]


@router.get("/admin/classification-suggestions", response_model=list[ClassificationSuggestionRead])
def list_classification_suggestions(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
    status_filter: Literal["pending", "approved", "rejected", "applied"] | None = Query(
        default=None, alias="status"
    ),
    suggestion_type: VALID_SUGGESTION_TYPES | None = Query(default=None),
    document_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ClassificationSuggestion]:
    stmt = select(ClassificationSuggestion).order_by(ClassificationSuggestion.created_at.desc())
    if status_filter:
        stmt = stmt.where(ClassificationSuggestion.status == status_filter)
    if suggestion_type:
        stmt = stmt.where(ClassificationSuggestion.suggestion_type == suggestion_type)
    if document_id:
        stmt = stmt.where(ClassificationSuggestion.document_id == document_id)
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/admin/classification-suggestions/counts")
def classification_suggestion_counts(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    rows = db.execute(
        select(ClassificationSuggestion.status, func.count(ClassificationSuggestion.id)).group_by(
            ClassificationSuggestion.status
        )
    ).all()
    return {status_value: count for status_value, count in rows}


@router.post(
    "/admin/classification-suggestions/{suggestion_id}/approve",
    response_model=ClassificationSuggestionRead,
)
def approve_classification_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ClassificationSuggestion:
    suggestion = db.get(ClassificationSuggestion, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    if suggestion.status not in ("pending", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Suggestion already in status '{suggestion.status}'",
        )
    suggestion.status = "approved"
    suggestion.reviewed_by_user_id = user.id
    suggestion.reviewed_at = datetime.utcnow()
    write_audit(
        db,
        user=user,
        action="classification_suggestion_approved",
        entity_type="classification_suggestion",
        entity_id=suggestion.id,
        details={
            "document_id": suggestion.document_id,
            "suggestion_type": suggestion.suggestion_type,
        },
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.post(
    "/admin/classification-suggestions/{suggestion_id}/reject",
    response_model=ClassificationSuggestionRead,
)
def reject_classification_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> ClassificationSuggestion:
    suggestion = db.get(ClassificationSuggestion, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    if suggestion.status not in ("pending", "approved"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Suggestion already in status '{suggestion.status}'",
        )
    suggestion.status = "rejected"
    suggestion.reviewed_by_user_id = user.id
    suggestion.reviewed_at = datetime.utcnow()
    write_audit(
        db,
        user=user,
        action="classification_suggestion_rejected",
        entity_type="classification_suggestion",
        entity_id=suggestion.id,
        details={
            "document_id": suggestion.document_id,
            "suggestion_type": suggestion.suggestion_type,
        },
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.get("/admin/learned-patterns", response_model=list[LearnedPatternRead])
def list_learned_patterns(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
    status_filter: Literal["active", "disabled", "pending"] | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[LearnedPattern]:
    stmt = select(LearnedPattern).order_by(
        LearnedPattern.applied_count.desc(), LearnedPattern.created_at.desc()
    )
    if status_filter:
        stmt = stmt.where(LearnedPattern.status == status_filter)
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


@router.post("/admin/learned-patterns/{pattern_id}/disable", response_model=LearnedPatternRead)
def disable_learned_pattern(
    pattern_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> LearnedPattern:
    pattern = db.get(LearnedPattern, pattern_id)
    if not pattern:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found")
    if pattern.status == "disabled":
        return pattern
    pattern.status = "disabled"
    pattern.updated_at = datetime.utcnow()
    write_audit(
        db,
        user=user,
        action="learned_pattern_disabled",
        entity_type="learned_pattern",
        entity_id=pattern.id,
        details={"pattern_value": pattern.pattern_value, "target_class": pattern.target_class},
    )
    db.commit()
    db.refresh(pattern)
    return pattern


@router.post("/admin/learned-patterns/{pattern_id}/enable", response_model=LearnedPatternRead)
def enable_learned_pattern(
    pattern_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> LearnedPattern:
    pattern = db.get(LearnedPattern, pattern_id)
    if not pattern:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found")
    pattern.status = "active"
    pattern.updated_at = datetime.utcnow()
    write_audit(
        db,
        user=user,
        action="learned_pattern_enabled",
        entity_type="learned_pattern",
        entity_id=pattern.id,
        details={"pattern_value": pattern.pattern_value, "target_class": pattern.target_class},
    )
    db.commit()
    db.refresh(pattern)
    try:
        emit_new_pattern_detected(
            pattern_id=pattern.id,
            pattern_type=pattern.pattern_type,
            pattern_value=pattern.pattern_value,
            target_class=pattern.target_class,
            target_action=pattern.target_action,
            applied_count=pattern.applied_count,
        )
    except Exception:
        logger.warning("webhook_new_pattern_failed pattern_id=%s", pattern.id)
    return pattern


@router.get("/admin/learning/health")
def learning_health(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> dict:
    """Aggregate health metrics for the learning loop.

    Returns suggestion counts, oldest pending age, stale count, top noisy
    clients (circuit-breaker input), and learned pattern stats. Drives the
    "Salud del learning loop" panel in the admin UI.
    """
    return health_snapshot(db)


@router.post("/admin/learning/auto-reject-stale")
def trigger_auto_reject_stale(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor")),
) -> dict:
    """Manually trigger the auto-reject job (admin escape hatch)."""
    from app.services.learning_health import (
        auto_reject_stale_suggestions,
        mark_stale_suggestions,
    )

    marked = mark_stale_suggestions(db)
    result = auto_reject_stale_suggestions(db)
    write_audit(
        db,
        user=_,
        action="learning_health_manual_trigger",
        entity_type="classification_suggestion",
        entity_id=None,
        details={"marked_stale": marked, **result},
    )
    db.commit()
    return {"marked_stale": marked, **result}
