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
from app.services.tenant_access import (
    access_scope_cache_key,
    filter_search_results_for_scope,
    resolve_user_access_scope,
)

router = APIRouter()


def csv_safe_cell(value) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    # Excel treats =, +, -, @, tab, and carriage return as formula prefixes.
    if stripped and stripped[0] in {"=", "+", "-", "@", "\t", "\r"}:
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
    # M-12: resolve the scope once and pass it to the service so
    # the SQL itself is restricted. The in-memory post-filter
    # below still runs as defense-in-depth (it strips rows whose
    # ``tags_json`` hit a denied tag).
    scope = resolve_user_access_scope(db, user)
    results = search_text(db, q, limit=limit, access_scope=scope)
    return filter_search_results_for_scope(db, results, scope)


@router.get("/exact", response_model=list[SearchResultRead])
@limiter.limit("60/minute")
def exact_search(
    request: Request,
    q: str = Query(min_length=1),
    kind: str = Query(
        default="reference",
        pattern="^(budget|order|invoice|delivery_note|reference|client|supplier)$",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SearchResult]:
    scope = resolve_user_access_scope(db, user)
    normalized = q.strip()
    results: list[SearchResult] = []
    if kind == "budget":
        budgets = db.scalars(
            select(Budget).where(Budget.budget_number == normalized).limit(limit)
        ).all()
        results = [
            _business_result(
                db, budget.document_id, f"Presupuesto {budget.budget_number}", 1.4, "exact_budget"
            )
            for budget in budgets
        ]
    elif kind == "order":
        orders = db.scalars(
            select(Order).where(Order.order_number == normalized).limit(limit)
        ).all()
        results = [
            _business_result(
                db, order.document_id, f"Pedido {order.order_number}", 1.4, "exact_order"
            )
            for order in orders
        ]
    elif kind in {"client", "supplier"}:
        budget_rows = []
        order_rows = []
        if kind == "client":
            budget_rows = list(
                db.scalars(
                    select(Budget).where(Budget.client_name.ilike(f"%{normalized}%")).limit(limit)
                ).all()
            )
            order_rows = list(
                db.scalars(
                    select(Order).where(Order.client_name.ilike(f"%{normalized}%")).limit(limit)
                ).all()
            )
        else:
            order_rows = list(
                db.scalars(
                    select(Order).where(Order.supplier_name.ilike(f"%{normalized}%")).limit(limit)
                ).all()
            )
        results = [
            _business_result(db, row.document_id, normalized, 1.1, f"{kind}_match")
            for row in [*budget_rows, *order_rows]
        ]
    else:
        entity_type = "reference" if kind == "reference" else kind
        entities = db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.normalized_value == normalized.lower())
            .limit(limit)
        ).all()
        results = [
            _business_result(
                db, entity.document_id, entity.entity_value, 1.3, f"exact_{entity_type}"
            )
            for entity in entities
        ]
    return filter_search_results_for_scope(db, results, scope)


@router.get("/guided", response_model=list[SearchResultRead])
def guided_search(
    request: Request,
    q: str = Query(min_length=1),
    mode: str = Query(
        default="text",
        pattern="^(budget|order|invoice|delivery_note|reference|client|supplier|text)$",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SearchResult]:
    scope = resolve_user_access_scope(db, user)
    normalized = q.strip()
    results: list[SearchResult] = []
    if mode == "text":
        results = search_text(db, normalized, limit=limit)
    elif mode == "budget":
        budgets = db.scalars(
            select(Budget).where(Budget.budget_number == normalized).limit(limit)
        ).all()
        results = [
            _business_result(
                db, budget.document_id, f"Presupuesto {budget.budget_number}", 1.4, "guided_budget"
            )
            for budget in budgets
        ]
    elif mode == "order":
        orders = db.scalars(
            select(Order).where(Order.order_number == normalized).limit(limit)
        ).all()
        results = [
            _business_result(
                db, order.document_id, f"Pedido {order.order_number}", 1.4, "guided_order"
            )
            for order in orders
        ]
    elif mode in {"client", "supplier"}:
        budget_rows = []
        order_rows = []
        if mode == "client":
            budget_rows = list(
                db.scalars(
                    select(Budget).where(Budget.client_name.ilike(f"%{normalized}%")).limit(limit)
                ).all()
            )
            order_rows = list(
                db.scalars(
                    select(Order).where(Order.client_name.ilike(f"%{normalized}%")).limit(limit)
                ).all()
            )
        else:
            order_rows = list(
                db.scalars(
                    select(Order).where(Order.supplier_name.ilike(f"%{normalized}%")).limit(limit)
                ).all()
            )
        results = [
            _business_result(db, row.document_id, normalized, 1.1, f"guided_{mode}")
            for row in [*budget_rows, *order_rows]
        ]
    else:
        entity_type = "reference" if mode == "reference" else mode
        entities = db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.entity_type == entity_type)
            .where(DocumentEntity.normalized_value == normalized.lower())
            .limit(limit)
        ).all()
        results = [
            _business_result(
                db, entity.document_id, entity.entity_value, 1.3, f"guided_{entity_type}"
            )
            for entity in entities
        ]
    return filter_search_results_for_scope(db, results, scope)


@router.post("/semantic", response_model=list[SearchResultRead])
@limiter.limit("30/minute")
def semantic_search(
    request: Request,
    payload: SemanticSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    scope = resolve_user_access_scope(db, user)
    results = search_semantic(
        db,
        payload.query,
        limit=payload.limit,
        filters=_filters_with_scope_cache(payload.filters, scope),
        access_scope=scope,
    )
    return filter_search_results_for_scope(db, results, scope)


@router.post("/hybrid", response_model=list[SearchResultRead])
@limiter.limit("30/minute")
def hybrid_search_endpoint(
    request: Request,
    payload: HybridSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    scope = resolve_user_access_scope(db, user)
    results = search_hybrid(
        db,
        payload.query,
        limit=payload.limit,
        filters=_filters_with_scope_cache(payload.filters, scope),
        access_scope=scope,
    )
    return filter_search_results_for_scope(db, results, scope)


@router.get("/export/csv")
@limiter.limit("10/minute")
def export_search_csv(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    results = search_text(db, q, limit=limit, access_scope=resolve_user_access_scope(db, user))
    results = filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))

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


def _business_result(
    db: Session, document_id: int, excerpt: str | None, score: float, source_type: str
) -> SearchResult:
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
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number.asc())
        .limit(1)
    )
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


def _filters_with_scope_cache(filters: dict | None, scope) -> dict:
    # This marker is an internal capability added by search_service only
    # after checking ``scope.is_admin``.  Never accept it from request JSON.
    scoped_filters = {
        key: value
        for key, value in (filters or {}).items()
        if key != "_allow_global_semantic_search"
    }
    if not scope.is_admin:
        scoped_filters["_cache_scope"] = access_scope_cache_key(scope)
    return scoped_filters


@router.get("/export/json")
@limiter.limit("10/minute")
def export_search_json(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    results = search_text(db, q, limit=limit, access_scope=resolve_user_access_scope(db, user))
    results = filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))

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
