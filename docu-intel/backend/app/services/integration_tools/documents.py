from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Document, DocumentBlock
from app.schemas.integration import IntegrationSource, IntegrationToolExecuteResponse
from app.services.integration_tools.common import (
    DocumentIdArgs,
    _can_access_document_for_context,
    _can_view_prices,
    _document_source,
    _filter_records_for_context,
    _model_dict,
    _response,
)
from app.services.integration_security import IntegrationContext
from app.services.redaction import redact_sensitive_text
from app.tools import internal


def execute_get_document(
    db: Session,
    context: IntegrationContext,
    args: DocumentIdArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    document = db.get(Document, args.document_id)
    if not _can_access_document_for_context(db, document, context):
        document = None
    data = _document_payload(document) if document else {"status": "not_found", "document_id": args.document_id}
    return _response(request_id, "get_document", context, data=data, sources=[] if not document else [_document_source(db, document, context)])


def execute_get_document_blocks(
    db: Session,
    context: IntegrationContext,
    args: DocumentIdArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    document = db.get(Document, args.document_id)
    if not _can_access_document_for_context(db, document, context):
        return _response(request_id, "get_document_blocks", context, data=[])
    blocks = internal.get_document_blocks(db, args.document_id, args.page_number)
    return _response(request_id, "get_document_blocks", context, data=[_block_payload(block, context) for block in blocks])


def execute_get_related_documents(
    db: Session,
    context: IntegrationContext,
    args: DocumentIdArgs,
    request_id: str,
) -> IntegrationToolExecuteResponse:
    documents = internal.get_related_documents(db, args.document_id)
    documents = [document for document in documents if _can_access_document_for_context(db, document, context)]
    return _response(request_id, "get_related_documents", context, data=[_document_payload(document) for document in documents])


def _document_payload(document: Document | None) -> dict:
    if not document:
        return {}
    return {
        "id": document.id,
        "original_filename": document.original_filename,
        "document_type": document.document_type,
        "status": document.status,
        "confidence": document.confidence,
        "page_count": document.page_count,
    }


def _block_payload(block: DocumentBlock, context: IntegrationContext) -> dict:
    text = block.text or ""
    if not _can_view_prices(context):
        text = redact_sensitive_text(text)
    return {
        "id": block.id,
        "document_id": block.document_id,
        "page_number": block.page_number,
        "block_type": block.block_type,
        "text": text,
        "confidence": block.confidence,
    }
