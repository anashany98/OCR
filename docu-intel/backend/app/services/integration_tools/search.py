from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.integration import IntegrationSource, IntegrationToolExecuteResponse
from app.services.integration_tools.common import (
    HybridSearchArgs,
    QueryArgs,
    _average,
    _can_view_prices,
    _filter_search_results_for_context,
    _redactions_for_policy,
    _response,
    _search_filters_for_context,
)
from app.services.integration_security import IntegrationContext
from app.services.redaction import redact_sensitive_text
from app.services.search_service import search_hybrid, search_text


def execute_search_documents(
    db: Session,
    context: IntegrationContext,
    args: QueryArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    filters = _search_filters_for_context(
        context,
        {"document_type": args.document_type} if args.document_type else None,
    )
    results = search_text(
        db,
        args.query,
        limit=args.limit * 5,
        filters=filters,
    )
    results = _filter_search_results_for_context(db, results, context)[: args.limit]
    return _search_response(request_id, "search_documents", context, results)


def execute_hybrid_search(
    db: Session,
    context: IntegrationContext,
    args: HybridSearchArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    filters = _search_filters_for_context(context, args.filters)
    filters["limit"] = args.limit
    results = search_hybrid(db, args.query, limit=args.limit * 5, filters=filters)
    results = _filter_search_results_for_context(db, results, context)[: args.limit]
    return _search_response(request_id, "hybrid_search", context, results)


def _search_response(
    request_id: str, tool: str, context: IntegrationContext, results
) -> IntegrationToolExecuteResponse:
    data = []
    sources = []
    for result in results:
        excerpt = result.excerpt or ""
        if not _can_view_prices(context):
            excerpt = redact_sensitive_text(excerpt)
        item = {
            "document_id": result.document_id,
            "filename": result.original_filename,
            "document_type": result.document_type,
            "status": result.status,
            "page_number": result.page_number,
            "block_id": result.block_id,
            "score": result.score,
            "excerpt": excerpt,
            "ocr_confidence": result.ocr_confidence,
        }
        data.append(item)
        sources.append(
            IntegrationSource(
                document_id=result.document_id,
                filename=result.original_filename,
                page_number=result.page_number,
                block_id=result.block_id,
                excerpt=excerpt,
                confidence=result.ocr_confidence,
            )
        )
    return _response(
        request_id,
        tool,
        context,
        data=data,
        sources=sources,
        confidence=_average([source.confidence for source in sources]),
        redactions=_redactions_for_policy(context),
    )
