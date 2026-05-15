from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import Plan, PlanDimension, PlanRoom, User
from app.schemas.business import PlanDimensionRead, PlanRead, PlanRoomRead, PlanRoomUpdate, PlanScaleUpdate
from app.services.audit import write_audit
from app.services.tenant_access import filter_records_by_document_scope, resolve_user_access_scope

router = APIRouter()
rooms_router = APIRouter()


@router.get("", response_model=list[PlanRead])
def list_plans(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Plan).order_by(Plan.created_at.desc())
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.limit(limit)).all())
    candidates = list(db.scalars(stmt.limit(max(limit * 5, 200))).all())
    return filter_records_by_document_scope(db, candidates, scope)[:limit]


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.get("/{plan_id}/rooms", response_model=list[PlanRoomRead])
def get_rooms(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PlanRoom]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


@router.get("/{plan_id}/dimensions", response_model=list[PlanDimensionRead])
def get_dimensions(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PlanDimension]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


@router.patch("/{plan_id}/scale", response_model=PlanRead)
def update_scale(
    plan_id: int,
    payload: PlanScaleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    write_audit(db, user=user, action="plan_scale_updated", entity_type="plan", entity_id=plan.id)
    db.commit()
    db.refresh(plan)
    return plan


@rooms_router.patch("/{room_id}", response_model=PlanRoomRead)
def update_room(
    room_id: int,
    payload: PlanRoomUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> PlanRoom:
    room = db.get(PlanRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Plan room not found")
    plan = db.get(Plan, room.plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan room not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    write_audit(db, user=user, action="plan_room_updated", entity_type="plan_room", entity_id=room.id)
    db.commit()
    db.refresh(room)
    return room
