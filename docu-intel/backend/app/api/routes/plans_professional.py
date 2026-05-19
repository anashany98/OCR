from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database.session import get_db
from app.models import Plan, PlanMeasurement, User
from app.schemas.professional import PlanMeasurementCreate, PlanMeasurementRead
from app.services.audit import write_audit
from app.services.tenant_access import filter_records_by_document_scope, resolve_user_access_scope

router = APIRouter()


@router.get("/{plan_id}/measurements", response_model=list[PlanMeasurementRead])
def list_plan_measurements(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PlanMeasurement]:
    plan = _accessible_plan(db, plan_id, user)
    return list(db.scalars(select(PlanMeasurement).where(PlanMeasurement.plan_id == plan.id).order_by(PlanMeasurement.created_at.desc())).all())


@router.post("/{plan_id}/measurements", response_model=PlanMeasurementRead)
def create_plan_measurement(
    plan_id: int,
    payload: PlanMeasurementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> PlanMeasurement:
    plan = _accessible_plan(db, plan_id, user)
    measurement = PlanMeasurement(
        plan_id=plan.id,
        has_discrepancy=_has_discrepancy(payload.value_m, payload.ocr_value_m),
        created_by_id=user.id,
        **payload.model_dump(),
    )
    db.add(measurement)
    write_audit(db, user=user, action="plan_measurement_created", entity_type="plan", entity_id=plan.id)
    db.commit()
    db.refresh(measurement)
    return measurement


def _accessible_plan(db: Session, plan_id: int, user: User) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


def _has_discrepancy(value_m: float | None, ocr_value_m: float | None) -> bool:
    if value_m is None or ocr_value_m is None:
        return False
    return abs(value_m - ocr_value_m) >= 0.05
