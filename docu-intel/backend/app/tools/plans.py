"""Plan-related tools for the AI agent.

Used to answer questions about architectural plans, rooms, and
dimensions.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Plan, PlanDimension, PlanRoom
from app.services.search_service import _escape_ilike_wildcards


def search_plans(db: Session, query: str):
    return list(
        db.scalars(
            select(Plan)
            .where(Plan.project_name.ilike(f"%{_escape_ilike_wildcards(query)}%"))
            .limit(20)
        ).all()
    )


def get_plan_rooms(db: Session, plan_id: int):
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


def get_plan_dimensions(db: Session, plan_id: int):
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


def get_room_measurements(db: Session, plan_id: int, room_name: str):
    pattern = f"%{_escape_ilike_wildcards(room_name)}%"
    return list(
        db.scalars(
            select(PlanRoom).where(PlanRoom.plan_id == plan_id).where(PlanRoom.name.ilike(pattern))
        ).all()
    )


def search_plan_room_measurements(db: Session, room_name: str):
    pattern = f"%{_escape_ilike_wildcards(room_name)}%"
    return list(
        db.execute(
            select(Plan, PlanRoom, Document)
            .join(PlanRoom, PlanRoom.plan_id == Plan.id)
            .join(Document, Document.id == Plan.document_id)
            .where(PlanRoom.name.ilike(pattern))
            .where(Document.deleted_at.is_(None))
            .order_by(PlanRoom.needs_review.asc(), Plan.created_at.desc())
            .limit(20)
        ).all()
    )
