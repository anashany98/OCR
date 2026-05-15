import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import User
from app.schemas.search import HybridSearchRequest, SearchResultRead, SemanticSearchRequest
from app.services.search_service import search_hybrid, search_semantic, search_text
from app.services.tenant_access import filter_search_results_for_scope, resolve_user_access_scope

router = APIRouter()


def csv_safe_cell(value) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in {"=", "+", "-", "@"}:
        return f"'{text}"
    return text


@router.get("/text", response_model=list[SearchResultRead])
def text_search(
    q: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    results = search_text(db, q, limit=limit if user.role == "admin" else limit * 5)
    return filter_search_results_for_scope(db, results, resolve_user_access_scope(db, user))[:limit]


@router.post("/semantic", response_model=list[SearchResultRead])
def semantic_search(
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
def hybrid_search_endpoint(
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
def export_search_csv(
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


@router.get("/export/json")
def export_search_json(
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
