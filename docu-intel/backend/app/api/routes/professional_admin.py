from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_roles
from app.core.security import hash_password
from app.database.session import get_db
from app.models import (
    Budget,
    Document,
    DocumentPage,
    NotificationRule,
    Plan,
    PlanMeasurement,
    SavedView,
    User,
    WorkItem,
    WorkItemComment,
)
from app.schemas.professional import (
    AdminUserCreate,
    AdminUserRead,
    AdminUserUpdate,
    NotificationRuleCreate,
    NotificationRuleRead,
    SavedViewCreate,
    SavedViewRead,
    WorkItemCommentCreate,
    WorkItemCommentRead,
    WorkItemCreate,
    WorkItemRead,
    WorkItemUpdate,
)
from app.services.audit import write_audit

router = APIRouter()


@router.get("/work-items", response_model=list[WorkItemRead])
def list_work_items(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> list[WorkItem]:
    stmt = (
        select(WorkItem)
        .options(selectinload(WorkItem.comments))
        .order_by(WorkItem.created_at.desc())
    )
    if status:
        stmt = stmt.where(WorkItem.status == status)
    return list(db.scalars(stmt.limit(200)).all())


@router.post("/work-items", response_model=WorkItemRead)
def create_work_item(
    payload: WorkItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> WorkItem:
    item = WorkItem(**payload.model_dump(), created_by_id=user.id)
    db.add(item)
    db.flush()
    write_audit(
        db, user=user, action="work_item_created", entity_type="work_item", entity_id=item.id
    )
    db.commit()
    return db.scalar(
        select(WorkItem).options(selectinload(WorkItem.comments)).where(WorkItem.id == item.id)
    )


@router.patch("/work-items/{work_item_id}", response_model=WorkItemRead)
def update_work_item(
    work_item_id: int,
    payload: WorkItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> WorkItem:
    item = db.get(WorkItem, work_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    if item.status in {"resolved", "ignored"} and not item.resolved_at:
        item.resolved_at = datetime.now(timezone.utc)
    write_audit(
        db, user=user, action="work_item_updated", entity_type="work_item", entity_id=item.id
    )
    db.commit()
    return db.scalar(
        select(WorkItem).options(selectinload(WorkItem.comments)).where(WorkItem.id == item.id)
    )


@router.post("/work-items/{work_item_id}/comments", response_model=WorkItemCommentRead)
def add_work_item_comment(
    work_item_id: int,
    payload: WorkItemCommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> WorkItemComment:
    if not db.get(WorkItem, work_item_id):
        raise HTTPException(status_code=404, detail="Work item not found")
    comment = WorkItemComment(work_item_id=work_item_id, user_id=user.id, body=payload.body)
    db.add(comment)
    write_audit(
        db, user=user, action="work_item_commented", entity_type="work_item", entity_id=work_item_id
    )
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/saved-views", response_model=list[SavedViewRead])
def list_saved_views(
    db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "gestor", "auditor"))
) -> list[SavedView]:
    return list(
        db.scalars(
            select(SavedView)
            .where((SavedView.user_id == user.id) | (SavedView.is_shared.is_(True)))
            .order_by(SavedView.created_at.desc())
        ).all()
    )


@router.post("/saved-views", response_model=SavedViewRead)
def create_saved_view(
    payload: SavedViewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor", "auditor")),
) -> SavedView:
    view = SavedView(user_id=user.id, **payload.model_dump())
    db.add(view)
    db.commit()
    db.refresh(view)
    return view


@router.get("/notification-rules", response_model=list[NotificationRuleRead])
def list_notification_rules(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "gestor", "auditor"))
) -> list[NotificationRule]:
    return list(
        db.scalars(select(NotificationRule).order_by(NotificationRule.created_at.desc())).all()
    )


@router.post("/notification-rules", response_model=NotificationRuleRead)
def create_notification_rule(
    payload: NotificationRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> NotificationRule:
    rule = NotificationRule(**payload.model_dump())
    db.add(rule)
    write_audit(db, user=user, action="notification_rule_created", entity_type="notification_rule")
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/users", response_model=list[AdminUserRead])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())).all())


@router.post("/users", response_model=AdminUserRead)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> User:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=409, detail="User email already exists")
    created = User(
        email=payload.email,
        name=payload.name,
        role=payload.role,
        is_active=payload.is_active,
        password_hash=hash_password(payload.password),
    )
    db.add(created)
    db.flush()
    write_audit(db, user=user, action="user_created", entity_type="user", entity_id=created.id)
    db.commit()
    db.refresh(created)
    return created


@router.patch("/users/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> User:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    data = payload.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        target.password_hash = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(target, field, value)
    write_audit(db, user=user, action="user_updated", entity_type="user", entity_id=target.id)
    db.commit()
    db.refresh(target)
    return target


@router.post("/demo/seed")
def seed_demo_data(
    db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))
) -> dict:
    document = Document(
        original_filename="demo_presupuesto_profesional.pdf",
        stored_filename=None,
        source_path="/demo/presupuestos/demo_presupuesto_profesional.pdf",
        file_hash="demo" + ("0" * 60),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=2048,
        document_type="presupuesto",
        status="needs_review",
        quality_status="processed_missing_fields",
        quality_flags_json=["missing_total"],
        confidence=0.62,
        page_count=1,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Presupuesto demo aceptado sin pedido. Total 1.245,60 EUR.",
            ocr_confidence=0.62,
        )
    )
    budget = Budget(
        document_id=document.id,
        budget_number="DEMO-2026-001",
        client_name="Hotel Demo Centro",
        total_amount=1245.6,
        currency="EUR",
        status="aceptado",
        accepted_detected=True,
        confidence=0.78,
    )
    db.add(budget)
    item = WorkItem(
        kind="missing_fields",
        title="Demo: revisar presupuesto",
        description="Documento de ejemplo con campos faltantes.",
        priority="normal",
        document_id=document.id,
        created_by_id=user.id,
    )
    db.add(item)

    plan_document = Document(
        original_filename="demo_plano_profesional.pdf",
        stored_filename=None,
        source_path="/demo/planos/demo_plano_profesional.pdf",
        file_hash="demo-plan" + ("1" * 55),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=4096,
        document_type="plano",
        status="processed",
        quality_status="processed_ok",
        quality_flags_json=[],
        confidence=0.81,
        page_count=1,
    )
    db.add(plan_document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=plan_document.id,
            page_number=1,
            text="Plano demo con escala 1:50 y cota 3.20 m.",
            ocr_confidence=0.74,
        )
    )
    plan = Plan(
        document_id=plan_document.id,
        project_name="Demo reforma habitaciones",
        scale_text="1:50",
        scale_ratio=50,
        scale_confidence=0.9,
        unit="m",
        has_valid_scale=True,
    )
    db.add(plan)
    db.flush()
    db.add(
        PlanMeasurement(
            plan_id=plan.id,
            label="Habitación demo",
            value_m=3.2,
            ocr_value_m=3.05,
            has_discrepancy=True,
            points_json=[],
            created_by_id=user.id,
        )
    )
    write_audit(db, user=user, action="demo_seeded", entity_type="document", entity_id=document.id)
    db.commit()
    return {"document_id": document.id, "work_item_id": item.id, "plan_id": plan.id}
