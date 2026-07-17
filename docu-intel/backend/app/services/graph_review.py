"""Admin review surface for the Graph RAG ``graph_review_queue``.

This service backs the ``/admin/graph-review-queue/*`` HTTP
endpoints. The surface stays deliberately small: list, decide. The
graph extraction worker is the only other writer of
``graph_review_queue``; this service is the only consumer of
decisions, and each decision is mirrored to ``audit_logs`` so the
human-in-the-loop trail is preserved.

Design constraints
------------------
* The admin scope reuses the project's existing
  ``require_roles("admin", "gestor", "auditor")`` gate. We do
  not invent a new role: the existing three already cover the
  review responsibilities and live in the access-scope model.
* Decisions are terminal: once a row is ``approved`` or
  ``rejected`` the queue filters it out of the default list. A
  follow-up review can re-create the row by re-running the
  extractor (the unique key is the relation row, not the
  review row).
* ``summary`` is computed lazily in Python instead of a
  database view so the same function powers both the
  production endpoint and the unit tests.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    GraphEntity,
    GraphRelation,
    GraphReviewQueue,
    User,
)
from app.services.audit import write_audit

DecisionLiteral = Literal["approved", "rejected", "escalated"]


def _summarise(item: GraphReviewQueue, relation: GraphRelation | None) -> str | None:
    """Build a short human-readable label for the review row.

    The summary is intentionally a single line so it fits the
    review dashboard's compact view. We surface the relation
    type when available, otherwise we fall back to the target
    type so the operator still has a clue while triaging.
    """
    if relation is not None:
        return f"relation {relation.id} — {relation.relation_type}"
    if item.target_type == "entity":
        return f"entity {item.target_id}"
    if item.target_type == "relation":
        return f"relation {item.target_id}"
    return None


def list_review_queue(
    db: Session,
    *,
    status: str = "pending",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int, int]:
    """Return ``(items, total_pending, total_escalated)`` for the dashboard.

    The list is keyed on ``(status, created_at)`` to match the
    index defined in migration ``0064_graph_rag_relational``; the
    page is bounded by ``limit`` (capped at 200) so a runaway
    queue cannot starve the API.
    """
    bounded_limit = max(1, min(int(limit), 200))
    bounded_offset = max(0, int(offset))

    items_query = (
        select(GraphReviewQueue, GraphRelation)
        .outerjoin(
            GraphRelation,
            (GraphReviewQueue.target_type == "relation")
            & (GraphRelation.id == GraphReviewQueue.target_id),
        )
        .where(GraphReviewQueue.status == status)
        .order_by(GraphReviewQueue.created_at.desc(), GraphReviewQueue.id.desc())
        .limit(bounded_limit)
        .offset(bounded_offset)
    )
    rows = db.execute(items_query).all()
    payload: list[dict] = []
    for item, relation in rows:
        payload.append(
            {
                "id": int(item.id),
                "target_type": item.target_type,
                "target_id": int(item.target_id),
                "status": item.status,
                "confidence": item.confidence,
                "rationale": item.rationale,
                "created_at": item.created_at,
                "submitted_by_job_id": int(item.submitted_by_job_id) if item.submitted_by_job_id else None,
                "summary": _summarise(item, relation),
            }
        )
    total_pending = int(
        db.scalar(select(func.count()).select_from(GraphReviewQueue).where(GraphReviewQueue.status == "pending"))
        or 0
    )
    total_escalated = int(
        db.scalar(select(func.count()).select_from(GraphReviewQueue).where(GraphReviewQueue.status == "escalated"))
        or 0
    )
    return payload, total_pending, total_escalated


def decide_review(
    db: Session,
    *,
    item_id: int,
    user: User,
    decision: DecisionLiteral,
    rationale: str | None,
) -> dict:
    """Apply ``decision`` to the review row and audit the change.

    Returns the updated row as a dict so the route handler can
    serialise it without re-querying. ``HTTPException(404)`` is
    raised when the row does not exist; ``HTTPException(409)`` is
    raised when the row has already been decided (idempotency
    contract for the frontend retry).
    """
    item = db.get(GraphReviewQueue, item_id)
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="graph review row not found")
    if item.status != "pending":
        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail=f"graph review row already in status '{item.status}'",
        )

    item.status = decision
    item.decided_by_user_id = user.id
    item.decided_at = datetime.now(UTC)
    if rationale:
        item.rationale = rationale

    # When the review confirms a relation, flip the underlying
    # relation's status to ``verified`` so the retrieval path
    # treats it as authoritative. Rejections leave the relation
    # in ``pending`` so it is filtered out by future RAG queries.
    if decision == "approved" and item.target_type == "relation":
        relation = db.get(GraphRelation, item.target_id)
        if relation is not None and relation.status != "verified":
            relation.status = "verified"

    write_audit(
        db,
        user=user,
        action="graph_review_decision",
        entity_type="graph_review_queue",
        entity_id=item.id,
        details={
            "decision": decision,
            "target_type": item.target_type,
            "target_id": int(item.target_id),
            "rationale": rationale,
        },
    )
    db.flush()
    return {
        "id": int(item.id),
        "status": item.status,
        "decided_by_user_id": int(item.decided_by_user_id) if item.decided_by_user_id else None,
        "decided_at": item.decided_at,
        "rationale": item.rationale,
    }


def iter_pending_for_target(target_type: str, target_id: int) -> Iterable[GraphReviewQueue]:
    """Helper used by the extractor worker to check whether a relation
    is already in the review queue (idempotency contract).
    """
    raise NotImplementedError("use a SQLAlchemy query directly; this helper is reserved for tests")


__all__ = [
    "decide_review",
    "list_review_queue",
]
