import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.database.session import get_db
from app.models import Budget, Document, DocumentEntity, DocumentPage, Order, User
from app.schemas.search import HybridSearchRequest, SearchResultRead, SemanticSearchRequest
from app.services.search_service import SearchResult, search_hybrid, search_semantic, search_text
from app.services.tenant_access import filter_search_results_for_scope, resolve_user_access_scope

router = APIRouter()


def csv_safe_cell(value) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in {"=", "+", "-", "@"}:
        return f"'{text}"
    return text


@router.get("/text", response_model=list[SearchResultRead])
@limiter.limit("60/minute")
def text_search(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    results = search_text(db, q, limit=limit if user.role == "admin" else limit * 5)
    return filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))[:limit]


@router.get("/exact", response_model=list[SearchResultRead])
@limiter.limit("60/minute")
def exact_search(
    request: Request,
    q: str = Query(min_length=1),
    kind: str = Query(default="reference", pattern="^(budget|order|invoice|delivery_note|reference|client|supplier)$"),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SearchResult]:
    scope = resolve_user_access_scope(db, user)
    normalized = q.strip()
    results: list[SearchResult] = []
    if kind == "budget":
        budgets = db.scalars(select(Budget).where(Budget.budget_number == normalized).limit(limit * 5)).all()
        results = [_business_result(db, budget.document_id, f"Presupuesto {budget.budget_number}", 1.4, "exact_budget") for budget in budgets]
    elif kind == "order":
        orders = db.scalars(select(Order).where(Order.order_number == normalized).limit(limit * 5)).all()
        results = [_business_result(db, order.document_id, f"Pedido {order.order_number}", 1.4, "exact_order") for order in orders]
    elif kind in {"client", "supplier"}:
        budget_rows = []
        order_rows = []
        if kind == "client":
            budget_rows = list(db.scalars(select(Budget).where(Budget.client_name.ilike(f"%{normalized}%")).limit(limit * 5)).all())
            order_rows = list(db.scalars(select(Order).where(Order.client_name.ilike(f"%{normalized}%")).limit(limit * 5)).all())
        else:
            order_rows = list(db.scalars(select(Order).where(Order.supplier_name.ilike(f"%{normalized}%")).limit(limit * 5)).all())
        results = [_business_result(db, row.document_id, normalized, 1.1, f"{kind}_match") for row in [*budget_rows, *order_rows]]
    else:
        entity_type = "reference" if kind == "reference" else kind
        entities = db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.normalized_value == normalized.lower())
            .limit(limit * 5)
        ).all()
        results = [_business_result(db, entity.document_id, entity.entity_value, 1.3, f"exact_{entity_type}") for entity in entities]
    return filter_search_results_for_scope(db, results, scope)[:limit]


@router.get("/guided", response_model=list[SearchResultRead])
def guided_search(
    request: Request,
    q: str = Query(min_length=1),
    mode: str = Query(default="text", pattern="^(budget|order|invoice|delivery_note|reference|client|supplier|text)$"),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SearchResult]:
    scope = resolve_user_access_scope(db, user)
    normalized = q.strip()
    results: list[SearchResult] = []
    if mode == "text":
        results = search_text(db, normalized, limit=limit if user.role == "admin" else limit * 5)
    elif mode == "budget":
        budgets = db.scalars(select(Budget).where(Budget.budget_number == normalized).limit(limit * 5)).all()
        results = [_business_result(db, budget.document_id, f"Presupuesto {budget.budget_number}", 1.4, "guided_budget") for budget in budgets]
    elif mode == "order":
        orders = db.scalars(select(Order).where(Order.order_number == normalized).limit(limit * 5)).all()
        results = [_business_result(db, order.document_id, f"Pedido {order.order_number}", 1.4, "guided_order") for order in orders]
    elif mode in {"client", "supplier"}:
        budget_rows = []
        order_rows = []
        if mode == "client":
            budget_rows = list(db.scalars(select(Budget).where(Budget.client_name.ilike(f"%{normalized}%")).limit(limit * 5)).all())
            order_rows = list(db.scalars(select(Order).where(Order.client_name.ilike(f"%{normalized}%")).limit(limit * 5)).all())
        else:
            order_rows = list(db.scalars(select(Order).where(Order.supplier_name.ilike(f"%{normalized}%")).limit(limit * 5)).all())
        results = [_business_result(db, row.document_id, normalized, 1.1, f"guided_{mode}") for row in [*budget_rows, *order_rows]]
    else:
        entity_type = "reference" if mode == "reference" else mode
        entities = db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.normalized_value == normalized.lower())
            .limit(limit * 5)
        ).all()
        results = [_business_result(db, entity.document_id, entity.entity_value, 1.3, f"guided_{entity_type}") for entity in entities]
    return filter_search_results_for_scope(db, results, scope)[:limit]


@router.post("/semantic", response_model=list[SearchResultRead])
@limiter.limit("30/minute")
def semantic_search(
    request: Request,
    payload: SemanticSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    results = search_semantic(
        db,
        payload.query,
        limit=payload.limit if user.role == "admin" else payload.limit * 5,
        filters=payload.filters,
    )
    return filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))[: payload.limit]


@router.post("/hybrid", response_model=list[SearchResultRead])
@limiter.limit("30/minute")
def hybrid_search_endpoint(
    request: Request,
    payload: HybridSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    results = search_hybrid(
        db,
        payload.query,
        limit=payload.limit if user.role == "admin" else payload.limit * 5,
        filters=payload.filters,
    )
    return filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))[: payload.limit]


@router.get("/export/csv")
@limiter.limit("10/minute")
def export_search_csv(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    results = search_text(db, q, limit=limit if user.role == "admin" else limit * 5)
    results = filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))[:limit]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["document_id", "filename", "type", "status", "page", "score", "excerpt"])
    for r in results:
        writer.writerow(
            [
                r.document_id,
                csv_safe_cell(r.original_filename),
                csv_safe_cell(r.document_type),
                csv_safe_cell(r.status),
                r.page_number,
                r.score,
                csv_safe_cell((r.excerpt or "")[:200]),
            ]
        )

    output.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=search_results_{timestamp}.csv"},
    )


def _business_result(db: Session, document_id: int, excerpt: str | None, score: float, source_type: str) -> SearchResult:
    document = db.get(Document, document_id)
    if not document:
        return SearchResult(
            document_id=document_id,
            original_filename="-",
            document_type="desconocido",
            status="missing",
            page_number=None,
            block_id=None,
            score=0.0,
            excerpt=excerpt or "",
            ocr_confidence=None,
            source_type=source_type,
        )
    page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.page_number.asc()).limit(1))
    return SearchResult(
        document_id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        status=document.status,
        page_number=page.page_number if page else None,
        block_id=None,
        score=score,
        excerpt=excerpt or (page.text[:240] if page and page.text else ""),
        ocr_confidence=page.ocr_confidence if page else None,
        source_type=source_type,
    )


@router.get("/export/json")
@limiter.limit("10/minute")
def export_search_json(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    results = search_text(db, q, limit=limit if user.role == "admin" else limit * 5)
    results = filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))[:limit]

    data = [
        {
            "document_id": r.document_id,
            "filename": r.original_filename,
            "type": r.document_type,
            "status": r.status,
            "page": r.page_number,
            "score": r.score,
            "excerpt": r.excerpt,
        }
        for r in results
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([json.dumps({"results": data, "count": len(data), "query": q}, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=search_results_{timestamp}.json"},
    )
