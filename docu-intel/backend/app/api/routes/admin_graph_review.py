"""HTTP routes for the Graph RAG review queue.

Mounted under the existing ``/admin`` prefix via
``app/api/routes/admin.py`` and ``app/api/router.py``. The
endpoints are intentionally thin: the heavy lifting lives in
``app.services.graph_review``.

Endpoints
---------
* ``GET /admin/graph-review-queue`` — list pending rows.
* ``POST /admin/graph-review-queue/{item_id}/decide`` — apply a
  decision (``approved`` / ``rejected`` / ``escalated``).

Both endpoints require the standard admin/g auditor/gestor
role; the gate is shared with the rest of the admin surface.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.models import User
from app.schemas.admin import (
    GraphReviewDecisionRequest,
    GraphReviewDecisionResponse,
    GraphReviewItemRead,
    GraphReviewQueueResponse,
)
from app.services.graph_review import decide_review, list_review_queue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/graph-review-queue", response_model=GraphReviewQueueResponse)
def get_graph_review_queue(
    status: str = Query("pending", pattern="^(pending|approved|rejected|escalated)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> GraphReviewQueueResponse:
    """List rows in the Graph RAG review queue (default: ``pending``)."""
    items, total_pending, total_escalated = list_review_queue(
        db, status=status, limit=limit, offset=offset
    )
    return GraphReviewQueueResponse(
        items=[GraphReviewItemRead(**item) for item in items],
        total_pending=total_pending,
        total_escalated=total_escalated,
    )


@router.post(
    "/graph-review-queue/{item_id}/decide",
    response_model=GraphReviewDecisionResponse,
)
def post_graph_review_decision(
    item_id: int,
    payload: GraphReviewDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> GraphReviewDecisionResponse:
    """Record the human decision for a review row."""
    result = decide_review(
        db,
        item_id=item_id,
        user=current_user,
        decision=payload.decision,
        rationale=payload.rationale,
    )
    return GraphReviewDecisionResponse(**result)
