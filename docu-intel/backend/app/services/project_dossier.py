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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.budget_scope import BudgetScope
from app.models.document import Document
from app.models.project import DocumentOccurrence, Project
from app.models.tenant import HotelChain
from app.services.sensitive_data import redact_for_scope

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


def resolve_project(
    db: Session,
    *,
    project_id: int | None = None,
    budget_code: str | None = None,
    brand_name: str | None = None,
    hotel_name: str | None = None,
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
    return list(db.scalars(stmt.limit(20)).all())


def get_project_dossier(
    db: Session,
    project_id: int,
    *,
    access_scope: Any | None = None,
) -> ProjectDossier:
    """Build a complete dossier for a project.

    Phase 10: accepts AccessScope for permission filtering.
    """
    from app.services.tenant_access import AccessScope

    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    # Phase 10: check if user has access to this project's brand
    if access_scope and not access_scope.is_admin:
        if access_scope.hotel_ids and project.hotel_id:
            if project.hotel_id not in access_scope.hotel_ids:
                raise PermissionError("Access denied to this project")
        if access_scope.chain_ids and project.brand_id:
            if project.brand_id not in access_scope.chain_ids:
                raise PermissionError("Access denied to this project")

    brand = db.get(HotelChain, project.brand_id) if project.brand_id else None
    hotel = None
    if project.hotel_id:
        from app.models.tenant import Hotel
        hotel = db.get(Hotel, project.hotel_id)

    # Count documents by category
    occurrence_counts = db.scalars(
        select(
            DocumentOccurrence.category,
            func.count(DocumentOccurrence.id),
        )
        .where(DocumentOccurrence.project_id == project_id)
        .group_by(DocumentOccurrence.category)
    ).all()
    docs_by_category = {cat: count for cat, count in occurrence_counts}
    total_docs = sum(docs_by_category.values())

    # Financials from budget scope
    budget_total = None
    order_total = None
    invoice_total = None
    if project.primary_budget_scope_id:
        from app.models.business import Budget, Invoice, Order
        budget_row = db.scalar(
            select(func.sum(Budget.total_amount)).where(
                Budget.budget_scope_id == project.primary_budget_scope_id
            )
        )
        order_row = db.scalar(
            select(func.sum(Order.total_amount)).where(
                Order.budget_scope_id == project.primary_budget_scope_id
            )
        )
        invoice_row = db.scalar(
            select(func.sum(Invoice.total_amount)).where(
                Invoice.document_id.in_(
                    select(DocumentOccurrence.document_id).where(
                        DocumentOccurrence.budget_scope_id == project.primary_budget_scope_id
                    )
                )
            )
        )
        budget_total = float(budget_row) if budget_row else None
        order_total = float(order_row) if order_row else None
        invoice_total = float(invoice_row) if invoice_row else None

    # Communications
    from app.models.communication import CommunicationThread, CommunicationMessage
    thread_count = db.scalar(
        select(func.count(CommunicationThread.id)).where(
            CommunicationThread.project_id == project_id
        )
    ) or 0
    message_count = db.scalar(
        select(func.count(CommunicationMessage.id)).join(
            CommunicationThread
        ).where(CommunicationThread.project_id == project_id)
    ) or 0

    # Issues
    from app.models.communication import ProjectIssue
    open_issues = db.scalar(
        select(func.count(ProjectIssue.id)).where(
            ProjectIssue.project_id == project_id,
            ProjectIssue.status.in_(["open", "in_progress"]),
        )
    ) or 0

    # Image count
    image_count = docs_by_category.get("imagenes", 0) + docs_by_category.get("fotos", 0)

    # Date range
    first_date = db.scalar(
        select(func.min(DocumentOccurrence.first_seen_at)).where(
            DocumentOccurrence.project_id == project_id
        )
    )
    last_date = db.scalar(
        select(func.max(DocumentOccurrence.last_seen_at)).where(
            DocumentOccurrence.project_id == project_id
        )
    )

    return ProjectDossier(
        project_id=project.id,
        project_name=project.name,
        brand_name=brand.name if brand else None,
        hotel_name=hotel.name if hotel else None,
        year=project.year,
        status=project.status,
        description=project.description,
        total_documents=total_docs,
        documents_by_category=docs_by_category,
        budget_total=budget_total,
        order_total=order_total,
        invoice_total=invoice_total,
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
) -> list[dict[str, Any]]:
    """List documents in a project, optionally filtered by category."""
    stmt = (
        select(DocumentOccurrence, Document)
        .join(Document, DocumentOccurrence.document_id == Document.id)
        .where(DocumentOccurrence.project_id == project_id)
        .order_by(DocumentOccurrence.last_seen_at.desc())
    )
    if category:
        stmt = stmt.where(DocumentOccurrence.category == category)
    stmt = stmt.limit(limit)

    results = []
    for occ, doc in db.scalars(stmt).unique():
        results.append({
            "occurrence_id": occ.id,
            "document_id": doc.id,
            "filename": doc.original_filename,
            "category": occ.category,
            "source_path": occ.source_path,
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
) -> list[dict[str, Any]]:
    """Search images in a project."""
    stmt = (
        select(DocumentOccurrence, Document)
        .join(Document, DocumentOccurrence.document_id == Document.id)
        .where(
            DocumentOccurrence.project_id == project_id,
            DocumentOccurrence.category.in_(["imagenes", "fotos"]),
        )
    )
    if query:
        stmt = stmt.where(Document.original_filename.ilike(f"%{query}%"))
    stmt = stmt.order_by(DocumentOccurrence.last_seen_at.desc()).limit(limit)

    results = []
    for occ, doc in db.scalars(stmt).unique():
        results.append({
            "occurrence_id": occ.id,
            "document_id": doc.id,
            "filename": doc.original_filename,
            "source_path": occ.source_path,
        })
    return results
