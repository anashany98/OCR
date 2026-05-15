from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Document, DocumentBlock, DocumentEntity, Order, Plan, PlanDimension, PlanRoom
from app.services.search_service import search_hybrid as run_hybrid_search
from app.services.search_service import search_text


def search_documents(db: Session, query: str, document_type: str | None = None, limit: int = 10):
    results = search_text(db, query, limit=limit)
    if document_type:
        results = [item for item in results if item.document_type == document_type]
    return results[:limit]


def get_document(db: Session, document_id: int):
    return db.get(Document, document_id)


def get_document_blocks(db: Session, document_id: int, page_number: int | None = None):
    stmt = select(DocumentBlock).where(DocumentBlock.document_id == document_id)
    if page_number:
        stmt = stmt.where(DocumentBlock.page_number == page_number)
    return list(db.scalars(stmt.limit(200)).all())


def search_budgets(db: Session, query: str, status: str | None = None):
    pattern = f"%{query}%"
    stmt = select(Budget).where((Budget.budget_number.ilike(pattern)) | (Budget.client_name.ilike(pattern)))
    if status:
        stmt = stmt.where(Budget.status == status)
    return list(db.scalars(stmt.limit(20)).all())


def get_budget_by_number(db: Session, budget_number: str):
    return db.scalar(select(Budget).where(Budget.budget_number == budget_number).limit(1))


def get_accepted_budgets_without_order(db: Session):
    ordered_budget_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
    return list(
        db.scalars(
            select(Budget)
            .where(Budget.accepted_detected.is_(True))
            .where(Budget.id.not_in(ordered_budget_ids))
            .limit(50)
        ).all()
    )


def search_orders(db: Session, query: str):
    pattern = f"%{query}%"
    stmt = select(Order).where((Order.order_number.ilike(pattern)) | (Order.supplier_name.ilike(pattern)))
    return list(db.scalars(stmt.limit(20)).all())


def get_order_by_number(db: Session, order_number: str):
    return db.scalar(select(Order).where(Order.order_number == order_number).limit(1))


def get_related_documents(db: Session, document_id: int):
    document = db.get(Document, document_id)
    if not document:
        return []
    related_ids = {document.id}
    budget = db.scalar(select(Budget).where(Budget.document_id == document.id).limit(1))
    if budget:
        related_ids.update(
            db.scalars(select(Order.document_id).where(Order.related_budget_id == budget.id)).all()
        )
    order = db.scalar(select(Order).where(Order.document_id == document.id).limit(1))
    if order and order.related_budget_id:
        related_budget = db.get(Budget, order.related_budget_id)
        if related_budget:
            related_ids.add(related_budget.document_id)
    return list(db.scalars(select(Document).where(Document.id.in_(related_ids))).all())


def search_plans(db: Session, query: str):
    return list(db.scalars(select(Plan).where(Plan.project_name.ilike(f"%{query}%")).limit(20)).all())


def get_plan_rooms(db: Session, plan_id: int):
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


def get_plan_dimensions(db: Session, plan_id: int):
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


def get_room_measurements(db: Session, plan_id: int, room_name: str):
    pattern = f"%{room_name}%"
    return list(
        db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id).where(PlanRoom.name.ilike(pattern))).all()
    )


def search_plan_room_measurements(db: Session, room_name: str):
    pattern = f"%{room_name}%"
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


def search_entities(db: Session, entity_type: str, value: str):
    return list(
        db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.entity_value.ilike(f"%{value}%"))
            .limit(50)
        ).all()
    )


def hybrid_search(db: Session, query: str, filters: dict | None = None):
    return run_hybrid_search(db, query, filters=(filters or {}), limit=(filters or {}).get("limit", 10))


def get_duplicate_documents(db: Session):
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "duplicate")
            .order_by(Document.id.desc())
            .limit(50)
        ).all()
    )


def get_ocr_review_documents(db: Session):
    return list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where((Document.status == "failed") | (Document.status == "needs_review") | (Document.confidence < 0.75))
            .order_by(Document.id.desc())
            .limit(50)
        ).all()
    )
