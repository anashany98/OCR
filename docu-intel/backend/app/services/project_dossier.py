"""Phase 8/10 — Project dossier tools.

Deterministic query layer before the LLM. Provides structured access
to project information: documents, financials, products, people,
communications, issues, timeline, and images.

Phase 10: All functions accept AccessScope and apply permissions
BEFORE returning data, not after.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Text, func, or_, select
from sqlalchemy.orm import Session

from app.models.budget_scope import BudgetScope
from app.models.document import Document
from app.models.project import DocumentOccurrence, Project
from app.models.tenant import HotelChain
from app.services.sensitive_data import redact_for_scope
from app.services.tenant_access import AccessScope, apply_access_predicates

logger = logging.getLogger("app.services.dossier")


@dataclass
class ProjectDossier:
    """Complete project information bundle."""
    project_id: int
    project_name: str
    brand_name: str | None = None
    hotel_name: str | None = None
    year: int | None = None
    status: str = "active"
    description: str = ""
    # Documents
    total_documents: int = 0
    documents_by_category: dict[str, int] = field(default_factory=dict)
    # Financials
    budget_total: float | None = None
    order_total: float | None = None
    invoice_total: float | None = None
    # People
    participant_count: int = 0
    # Communications
    thread_count: int = 0
    message_count: int = 0
    # Issues
    open_issues: int = 0
    # Images
    image_count: int = 0
    # Metadata
    first_document_at: str | None = None
    last_document_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Stable DTO consumed by tools and the chat layer."""
        return {
            "project": {"id": self.project_id, "name": self.project_name, "status": self.status},
            "identity": {"year": self.year, "brand": self.brand_name, "hotel": self.hotel_name},
            "description": {"text": self.description, "deterministic": True},
            "documents": {"unique_documents": self.total_documents, "occurrences": self.total_documents, "by_category": self.documents_by_category},
            "financials": {"totals": {"budget": self.budget_total, "orders": self.order_total, "invoices": self.invoice_total}},
            "people": {"count": self.participant_count},
            "communications": {"threads": self.thread_count, "messages": self.message_count},
            "issues": {"open_count": self.open_issues},
            "images": {"count": self.image_count},
            "timeline": {"first": self.first_document_at, "last": self.last_document_at},
            "data_gaps": [],
            "sources": [],
        }


def resolve_project(
    db: Session,
    *,
    project_id: int | None = None,
    budget_code: str | None = None,
    brand_name: str | None = None,
    hotel_name: str | None = None,
    access_scope: AccessScope | None = None,
) -> list[Project]:
    """Resolve projects by various identifiers.

    Returns a list because brand+hotel may match multiple projects.
    """
    stmt = select(Project)
    if project_id:
        stmt = stmt.where(Project.id == project_id)
    elif budget_code:
        stmt = stmt.join(BudgetScope, Project.primary_budget_scope_id == BudgetScope.id).where(
            BudgetScope.budget_code == budget_code
        )
    elif brand_name:
        stmt = stmt.join(HotelChain, Project.brand_id == HotelChain.id).where(
            HotelChain.name.ilike(f"%{brand_name}%")
        )
        if hotel_name:
            from app.models.tenant import Hotel
            stmt = stmt.join(Hotel, Project.hotel_id == Hotel.id).where(
                Hotel.name.ilike(f"%{hotel_name}%")
            )
    else:
        return []
    projects = list(db.scalars(stmt.limit(20)).all())
    if access_scope is None:
        return projects
    return [project for project in projects if _scope_allows_project(project, access_scope)]


def require_project_access(db: Session, project: Project, access_scope: AccessScope | None) -> None:
    """Reject a project before any dossier data is queried or rendered."""
    if access_scope is None or not _scope_allows_project(project, access_scope):
        raise PermissionError("Access denied to this project")


def _scope_allows_project(project: Project, scope: AccessScope) -> bool:
    if scope.is_admin or scope.allow_all_hotels:
        return True
    return bool(
        project.hotel_id is not None and project.hotel_id in scope.hotel_ids
    ) or project.brand_id in scope.chain_ids


def get_project_dossier(
    db: Session,
    project_id: int,
    *,
    access_scope: Any | None = None,
) -> ProjectDossier:
    """Build a complete dossier for a project.

    Phase 10: accepts AccessScope for permission filtering.
    """
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    require_project_access(db, project, access_scope)

    brand = db.get(HotelChain, project.brand_id) if project.brand_id else None
    hotel = None
    if project.hotel_id:
        from app.models.tenant import Hotel
        hotel = db.get(Hotel, project.hotel_id)

    # Count documents by category
    occurrence_counts_stmt = (
        select(
            DocumentOccurrence.category,
            func.count(DocumentOccurrence.id),
        )
        .join(Document, DocumentOccurrence.document_id == Document.id)
        .where(DocumentOccurrence.project_id == project_id)
        .group_by(DocumentOccurrence.category)
    )
    occurrence_counts = db.execute(
        apply_access_predicates(occurrence_counts_stmt, access_scope, document_column=Document.id)
    ).all()
    docs_by_category = {cat: count for cat, count in occurrence_counts}
    total_docs = sum(docs_by_category.values())

    # Financials from budget scope
    budget_total = None
    order_total = None
    invoice_total = None
    visible_document_ids = list(db.scalars(
        apply_access_predicates(
            select(DocumentOccurrence.document_id)
            .join(Document, DocumentOccurrence.document_id == Document.id)
            .where(DocumentOccurrence.project_id == project_id),
            access_scope,
            document_column=Document.id,
        )
    ).all())
    if project.primary_budget_scope_id and visible_document_ids:
        from app.models.business import Budget, Invoice, Order
        budget_row = db.scalar(
            select(func.sum(Budget.total_amount)).where(
                Budget.budget_scope_id == project.primary_budget_scope_id,
                Budget.document_id.in_(visible_document_ids),
            )
        )
        order_row = db.scalar(
            select(func.sum(Order.total_amount)).where(
                Order.budget_scope_id == project.primary_budget_scope_id,
                Order.document_id.in_(visible_document_ids),
            )
        )
        invoice_row = db.scalar(
            select(func.sum(Invoice.total_amount)).where(
                Invoice.document_id.in_(
                    visible_document_ids
                )
            )
        )
        budget_total = float(budget_row) if budget_row else None
        order_total = float(order_row) if order_row else None
        invoice_total = float(invoice_row) if invoice_row else None

    # Communications
    from app.models.communication import CommunicationThread, CommunicationMessage
    message_count = db.scalar(
        select(func.count(CommunicationMessage.id)).join(
            CommunicationThread
        ).where(
            CommunicationThread.project_id == project_id,
            CommunicationMessage.document_id.in_(visible_document_ids),
        )
    ) or 0
    thread_count = db.scalar(
        select(func.count(func.distinct(CommunicationMessage.thread_id)))
        .join(CommunicationThread)
        .where(
            CommunicationThread.project_id == project_id,
            CommunicationMessage.document_id.in_(visible_document_ids),
        )
    ) or 0

    # Issues
    from app.models.communication import ProjectIssue
    open_issues = db.scalar(
        select(func.count(ProjectIssue.id)).where(
            ProjectIssue.project_id == project_id,
            ProjectIssue.source_document_id.in_(visible_document_ids),
            ProjectIssue.status.in_(["open", "in_progress"]),
        )
    ) or 0

    # Image count
    image_count = docs_by_category.get("imagenes", 0) + docs_by_category.get("fotos", 0)

    # Date range
    first_date = db.scalar(
        select(func.min(DocumentOccurrence.first_seen_at)).where(
            DocumentOccurrence.project_id == project_id
        ).where(DocumentOccurrence.document_id.in_(visible_document_ids))
    )
    last_date = db.scalar(
        select(func.max(DocumentOccurrence.last_seen_at)).where(
            DocumentOccurrence.project_id == project_id
        ).where(DocumentOccurrence.document_id.in_(visible_document_ids))
    )

    return ProjectDossier(
        project_id=project.id,
        project_name=project.name,
        brand_name=brand.name if brand else None,
        hotel_name=hotel.name if hotel else None,
        year=project.year,
        status=project.status,
        description=redact_for_scope(
            {"description": project.description}, access_scope.can_view_prices, access_scope.is_admin
        )["description"],
        total_documents=total_docs,
        documents_by_category=docs_by_category,
        budget_total=budget_total if access_scope.can_view_prices else None,
        order_total=order_total if access_scope.can_view_prices else None,
        invoice_total=invoice_total if access_scope.can_view_prices else None,
        participant_count=0,
        thread_count=thread_count,
        message_count=message_count,
        open_issues=open_issues,
        image_count=image_count,
        first_document_at=str(first_date) if first_date else None,
        last_document_at=str(last_date) if last_date else None,
    )


def list_project_documents(
    db: Session,
    project_id: int,
    *,
    category: str | None = None,
    limit: int = 100,
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    """List documents in a project, optionally filtered by category."""
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    stmt = (
        select(DocumentOccurrence, Document)
        .join(Document, DocumentOccurrence.document_id == Document.id)
        .where(DocumentOccurrence.project_id == project_id)
        .order_by(DocumentOccurrence.last_seen_at.desc())
    )
    if category:
        stmt = stmt.where(DocumentOccurrence.category == category)
    stmt = apply_access_predicates(stmt, access_scope, document_column=Document.id).limit(limit)

    results = []
    for occ, doc in db.execute(stmt).unique().all():
        results.append({
            "occurrence_id": occ.id,
            "document_id": doc.id,
            "filename": doc.original_filename,
            "category": occ.category,
            "source_path": occ.source_path if access_scope.is_admin else None,
            "first_seen": str(occ.first_seen_at),
            "last_seen": str(occ.last_seen_at),
        })
    return results


def search_project_images(
    db: Session,
    project_id: int,
    *,
    query: str | None = None,
    limit: int = 50,
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    """Search images in a project."""
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    stmt = (
        select(DocumentOccurrence, Document, ImageAnalysis)
        .join(Document, DocumentOccurrence.document_id == Document.id)
        .outerjoin(ImageAnalysis, ImageAnalysis.document_id == Document.id)
        .where(
            DocumentOccurrence.project_id == project_id,
            DocumentOccurrence.category.in_(["imagenes", "fotos"]),
        )
    )
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(or_(
            Document.original_filename.ilike(pattern),
            ImageAnalysis.description.ilike(pattern),
            ImageAnalysis.labels_json.cast(Text).ilike(pattern),
            ImageAnalysis.room_or_zone.ilike(pattern),
        ))
    stmt = apply_access_predicates(
        stmt, access_scope, document_column=Document.id
    ).order_by(DocumentOccurrence.last_seen_at.desc()).limit(limit)

    results = []
    for occ, doc, analysis in db.execute(stmt).unique().all():
        results.append({
            "occurrence_id": occ.id,
            "document_id": doc.id,
            "filename": doc.original_filename,
            "source_path": occ.source_path if access_scope.is_admin else None,
            "labels": analysis.labels_json if analysis else [],
            "description": analysis.description if analysis else None,
            "zone": analysis.room_or_zone if analysis else None,
            "confidence": analysis.confidence if analysis else None,
        })
    return results


def get_project_financials(db: Session, project_id: int, *, access_scope: AccessScope | None) -> dict[str, Any]:
    """Return source-backed financial records without crossing document scope."""
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    ids = _visible_document_ids(db, project_id, access_scope)
    from app.models.business import Budget, Invoice, Order
    def rows(model, number_field: str) -> list[dict[str, Any]]:
        result = []
        for row in db.scalars(select(model).where(model.document_id.in_(ids))).all():
            result.append({"id": row.id, "number": getattr(row, number_field, None), "total": float(row.total_amount) if row.total_amount is not None and access_scope.can_view_prices else None, "currency": row.currency if access_scope.can_view_prices else None, "source_document_id": row.document_id})
        return result
    budgets, orders, invoices = rows(Budget, "budget_number"), rows(Order, "order_number"), rows(Invoice, "invoice_number")
    return {"budgets": budgets, "orders": orders, "invoices": invoices, "totals": {"budget": _sum_amounts(budgets), "orders": _sum_amounts(orders), "invoices": _sum_amounts(invoices)}}


def get_project_products(db: Session, project_id: int, *, access_scope: AccessScope | None) -> list[dict[str, Any]]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    ids = _visible_document_ids(db, project_id, access_scope)
    from app.models.business import Budget, BudgetLine, Order, OrderLine
    products: list[dict[str, Any]] = []
    for model, line_model, parent_key in ((Budget, BudgetLine, "budget_id"), (Order, OrderLine, "order_id")):
        stmt = select(line_model, model).join(model, getattr(line_model, parent_key) == model.id).where(model.document_id.in_(ids))
        for line, parent in db.execute(stmt).all():
            products.append({"reference": line.reference, "description": line.description, "quantity": line.quantity, "unit": line.unit, "unit_price": float(line.unit_price) if line.unit_price is not None and access_scope.can_view_prices else None, "total_price": float(line.total_price) if line.total_price is not None and access_scope.can_view_prices else None, "source_document_id": parent.document_id})
    return products


def _visible_document_ids(db: Session, project_id: int, scope: AccessScope) -> list[int]:
    stmt = apply_access_predicates(select(DocumentOccurrence.document_id).join(Document).where(DocumentOccurrence.project_id == project_id), scope, document_column=Document.id)
    return list(db.scalars(stmt).all())


def _sum_amounts(rows: list[dict[str, Any]]) -> float | None:
    amounts = [row["total"] for row in rows if row["total"] is not None]
    return round(sum(amounts), 2) if amounts else None


def get_project_people(db: Session, project_id: int, *, access_scope: AccessScope | None) -> list[dict[str, Any]]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    from app.models.communication import Contact, ProjectParticipant
    stmt = select(ProjectParticipant, Contact).outerjoin(Contact, ProjectParticipant.contact_id == Contact.id).where(ProjectParticipant.project_id == project_id)
    people = []
    for participant, contact in db.execute(stmt).all():
        payload = redact_for_scope({"name": contact.name if contact else None, "email": contact.email if contact else participant.email, "phone": contact.phone if contact else None}, access_scope.can_view_prices, access_scope.is_admin)
        people.append({**payload, "role": participant.role, "confidence": participant.role_confidence, "source": {"project_id": project_id}})
    return people


def get_project_communications(db: Session, project_id: int, *, access_scope: AccessScope | None) -> list[dict[str, Any]]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    ids = _visible_document_ids(db, project_id, access_scope)
    from app.models.communication import CommunicationMessage, CommunicationThread
    stmt = select(CommunicationMessage, CommunicationThread).join(CommunicationThread).where(CommunicationThread.project_id == project_id, CommunicationMessage.document_id.in_(ids)).order_by(CommunicationMessage.sent_at)
    out = []
    for message, thread in db.execute(stmt).all():
        payload = redact_for_scope({"subject": message.subject, "from": message.from_email, "body": message.body_text}, access_scope.can_view_prices, access_scope.is_admin)
        out.append({"thread_id": thread.id, "message_id": message.id, "sent_at": str(message.sent_at) if message.sent_at else None, **payload, "source_document_id": message.document_id})
    return out


def get_project_issues(db: Session, project_id: int, *, access_scope: AccessScope | None) -> list[dict[str, Any]]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    ids = _visible_document_ids(db, project_id, access_scope)
    from app.models.communication import ProjectIssue
    rows = db.scalars(select(ProjectIssue).where(ProjectIssue.project_id == project_id, ProjectIssue.source_document_id.in_(ids)).order_by(ProjectIssue.created_at)).all()
    return [{"id": row.id, "title": row.title, "description": redact_for_scope({"description": row.description}, access_scope.can_view_prices, access_scope.is_admin)["description"], "severity": row.severity, "status": row.status, "source_document_id": row.source_document_id} for row in rows]


def get_project_timeline(db: Session, project_id: int, *, access_scope: AccessScope | None) -> list[dict[str, Any]]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    require_project_access(db, project, access_scope)
    ids = _visible_document_ids(db, project_id, access_scope)
    from app.models.communication import ProjectEvent
    rows = db.scalars(select(ProjectEvent).where(ProjectEvent.project_id == project_id, ProjectEvent.source_document_id.in_(ids)).order_by(ProjectEvent.event_date, ProjectEvent.created_at)).all()
    return [{"type": row.event_type, "title": row.title, "date": str(row.event_date or row.created_at), "source_document_id": row.source_document_id, "source_message_id": row.source_message_id} for row in rows]
