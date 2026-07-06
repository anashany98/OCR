"""Hyper-Extract — REST endpoints.

Mounted under ``/documents`` in :mod:`app.api.router`. Endpoints:

* ``POST /documents/{document_id}/extract`` — run an extraction on the
  document's OCR text and persist the result.
* ``POST /documents/{document_id}/extract/retry`` — explicit retry,
  same semantics as ``POST /extract``.
* ``GET  /documents/{document_id}/extraction`` — return the latest
  stored extraction (no provider call).
* ``GET  /documents/{document_id}/extractions`` — full history, newest
  first. Useful for the future review panel.

All endpoints require authentication (``admin`` or ``gestor``) so a
regular operator cannot trigger a paid provider call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, DocumentExtraction, DocumentPage, User
from app.schemas.hyperextract import (
    DocumentExtractionRead,
    HyperExtractEnvelope,
    HyperExtractRequest,
)
from app.services.hyperextract.service import (
    HyperExtractService,
    get_hyperextract_service,
)
from app.services.tenant_access import can_access_document, resolve_user_access_scope

router = APIRouter()
logger = logging.getLogger(__name__)


def _load_ocr_text(db: Session, document_id: int) -> str:
    """Concatenate every page's OCR text in order.

    Hyper-Extract needs the full document text, not just one page. We
    pull from ``document_pages`` (the canonical OCR store) and skip
    pages that have no text yet — the caller is responsible for making
    sure the OCR has run before invoking the extract endpoint.
    """
    rows = db.execute(
        select(DocumentPage.page_number, DocumentPage.text)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc())
    ).all()
    return "\n\n".join(text for _, text in rows if text)


def _build_metadata(document: Document, document_type: str | None) -> dict:
    return {
        "filename": document.original_filename,
        "document_type": document_type or document.document_type,
        "page_count": document.page_count,
    }


def _persist_result(
    db: Session,
    *,
    document: Document,
    payload: dict,
) -> DocumentExtraction | None:
    """Persist a Hyper-Extract envelope.

    The status ``disabled`` is **not** persisted: there is nothing to
    audit and the caller already knows why nothing happened. Every other
    status (``success``, ``failed``, ``pending``) becomes a row.

    When the LLM returns a ``document_type`` different from the one
    stored on the document, we update ``documents.document_type`` so
    the rest of the pipeline (chat IA, search, lists) sees the LLM's
    verdict. The update is conservative: we only overwrite when the
    extraction succeeded AND the LLM emitted a non-empty type.
    """
    if payload.get("status") == "disabled":
        return None
    row = DocumentExtraction(
        document_id=document.id,
        document_type=payload.get("document_type"),
        provider=payload.get("provider"),
        model=payload.get("model"),
        status=str(payload.get("status") or "pending"),
        fields_json=payload.get("fields") or {},
        entities_json=payload.get("entities") or [],
        relations_json=payload.get("relations") or [],
        warnings_json=payload.get("warnings") or [],
        raw_output_json=payload.get("raw_output") or None,
        error_message=payload.get("error_message"),
        latency_ms=int(payload.get("latency_ms") or 0),
    )
    db.add(row)
    # Promote the LLM-detected document_type to the main document row
    # when extraction succeeded. The chat IA prompt no longer relies
    # on this field (it classifies from the text directly), but the
    # rest of the system (filters, lists, KPIs) still benefits from a
    # accurate type label.
    new_type = payload.get("document_type")
    if (
        payload.get("status") == "success"
        and isinstance(new_type, str)
        and new_type.strip()
        and new_type.strip().lower() not in {"desconocido", "unknown", ""}
    ):
        normalised = new_type.strip().lower()
        current = (document.document_type or "").strip().lower()
        if normalised != current:
            document.document_type = normalised
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/extract",
    response_model=HyperExtractEnvelope,
    summary="Run Hyper-Extract on a document's OCR text",
)
def extract_document(
    document_id: int,
    payload: HyperExtractRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
    service: HyperExtractService = Depends(get_hyperextract_service),
) -> HyperExtractEnvelope:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")

    request = payload or HyperExtractRequest()
    text = _load_ocr_text(db, document_id)
    if not text.strip():
        # The OCR pipeline hasn't produced text yet — refuse rather
        # than call the provider with an empty prompt.
        envelope = HyperExtractEnvelope(
            enabled=service.is_enabled(),
            status="skipped",
            document_id=document.id,
            document_type=request.document_type,
            warnings=["no_ocr_text_available"],
        ).model_dump()
        _persist_result(db, document=document, payload=envelope)
        return envelope  # type: ignore[return-value]

    # ``force=True`` lets an operator run an extraction even when the
    # feature flag is off — useful for ad-hoc validation in lower
    # environments. In production this should remain False; the
    # default keeps the safety guarantee.
    if not service.is_enabled() and not request.force:
        envelope = HyperExtractEnvelope(
            enabled=False,
            status="disabled",
            document_id=document.id,
            document_type=request.document_type,
            warnings=["hyperextract_disabled"],
        ).model_dump()
        return envelope  # type: ignore[return-value]

    metadata = _build_metadata(document, request.document_type)
    envelope = service.extract_from_text(
        document_id=document.id,
        text=text,
        document_type=request.document_type,
        metadata=metadata,
    )
    # When ``force=True`` with the feature flag off, mark the envelope
    # as ``enabled=False`` so callers can see why the call still ran.
    envelope.setdefault("enabled", service.is_enabled() or request.force)
    _persist_result(db, document=document, payload=envelope)
    return envelope  # type: ignore[return-value]


@router.post(
    "/{document_id}/extract/retry",
    response_model=HyperExtractEnvelope,
    summary="Alias for POST /extract used by the admin UI",
)
def retry_extraction(
    document_id: int,
    payload: HyperExtractRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
    service: HyperExtractService = Depends(get_hyperextract_service),
) -> HyperExtractEnvelope:
    # Same handler — kept as a separate route so the URL is intuitive
    # and the audit log captures the operator intent ("retry").
    request = payload or HyperExtractRequest(force=True)
    return extract_document(
        document_id=document_id,
        payload=request,
        db=db,
        user=user,
        service=service,
    )


@router.get(
    "/{document_id}/extraction",
    response_model=DocumentExtractionRead | None,
    summary="Return the latest persisted Hyper-Extract result",
)
def get_latest_extraction(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> DocumentExtractionRead | None:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    row = db.scalar(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document_id)
        .order_by(DocumentExtraction.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    return DocumentExtractionRead.model_validate(row)


@router.get(
    "/{document_id}/extractions",
    response_model=list[DocumentExtractionRead],
    summary="Return the full Hyper-Extract history (newest first)",
)
def list_extractions(
    document_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> list[DocumentExtractionRead]:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    rows = db.scalars(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document_id)
        .order_by(DocumentExtraction.created_at.desc())
        .limit(limit)
    ).all()
    return [DocumentExtractionRead.model_validate(r) for r in rows]


@router.get(
    "/hyperextract/status",
    response_model=dict,
    summary="Lightweight health probe for Hyper-Extract",
)
def hyperextract_status(
    user: User = Depends(get_current_user),
    service: HyperExtractService = Depends(get_hyperextract_service),
) -> dict:
    """Return whether Hyper-Extract is configured and which templates are loaded."""
    return {
        "enabled": service.is_enabled(),
        "provider": settings.hyperextract_provider,
        "model": settings.hyperextract_model,
        "base_url_configured": bool(settings.hyperextract_base_url),
        "timeout_seconds": settings.hyperextract_timeout_seconds,
        "run_in_pipeline": settings.hyperextract_run_in_pipeline,
        "default_type": settings.hyperextract_default_type,
        "templates": service.list_available_templates(),
        "checked_at": datetime.now(UTC).isoformat(),
    }
