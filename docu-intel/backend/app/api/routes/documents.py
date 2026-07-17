import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.rate_limit import limiter
from app.database.session import get_db
from app.models import Document, DocumentBlock, DocumentEntity, DocumentPage, User
from app.schemas.documents import (
    BulkReprocessRequest,
    BulkReprocessResponse,
    DocumentBlockRead,
    DocumentEntityRead,
    DocumentGraphRelationsResponse,
    DocumentPageRead,
    DocumentRead,
    GraphRelationEvidenceRead,
    GraphRelationRead,
    UploadResponse,
)
from app.schemas.jobs import ExtractionJobRead
from app.services.audit import write_audit
from app.services.document_registration_service import normalize_untrusted_relative_path
from app.services.document_service import register_upload, reprocess_document, soft_delete_document
from app.services.graph_query import (
    RelationEvidenceRow,
    RelationRow,
    list_evidence_quotes,
    list_relations_for_document,
)
from app.services.operations import BulkReprocessFilters, bulk_reprocess_documents
from app.services.tenant_access import (
    apply_access_predicates,
    can_access_document,
    filter_documents_for_scope,
    resolve_user_access_scope,
)

router = APIRouter()

logger = logging.getLogger(__name__)


class BatchUploadItem(BaseModel):
    document_id: int
    original_filename: str
    status: str
    job_id: int | None


class BatchUploadResponse(BaseModel):
    uploaded: int
    duplicates: int
    failed: int
    documents: list[BatchUploadItem]


@router.post("/upload", response_model=UploadResponse)
@limiter.limit("30/minute")
def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> UploadResponse:
    try:
        document, job = register_upload(db, filename=file.filename, stream=file.file, user=user)
    except ValueError as exc:
        if "max_upload_size" in str(exc):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise
    return UploadResponse(
        document=DocumentRead.model_validate(document), job_id=job.id if job else None
    )


@router.post("/upload/batch", response_model=BatchUploadResponse)
@limiter.limit("10/minute")
def upload_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    relative_paths: str = Form(default="[]"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    import json as _json

    try:
        parsed_paths = _json.loads(relative_paths) if relative_paths else []
    except _json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail="relative_paths must be a JSON list of strings"
        ) from exc

    if parsed_paths and len(parsed_paths) != len(files):
        raise HTTPException(
            status_code=422,
            detail=f"relative_paths length ({len(parsed_paths)}) must match files length ({len(files)})",
        )

    uploaded = 0
    duplicates = 0
    failed = 0
    results = []

    for index, file in enumerate(files):
        # Preserve the relative path inside the selected folder so the IA
        # agent can use the directory tree as a classification hint (e.g.
        # /presupuestos/245745/foo.pdf ⇒ budget code 245745).
        raw_path = parsed_paths[index] if parsed_paths else None
        source_path = None
        if raw_path:
            try:
                source_path = normalize_untrusted_relative_path(raw_path, user_id=user.id)
            except ValueError as exc:
                logger.warning(
                    "batch_upload_rejected_path user=%d path=%r reason=%s",
                    user.id,
                    raw_path,
                    exc,
                )
                failed += 1
                results.append(
                    BatchUploadItem(
                        document_id=0,
                        original_filename=file.filename or "unknown",
                        status="rejected",
                        job_id=None,
                    )
                )
                continue
        try:
            document, job = register_upload(
                db,
                filename=file.filename,
                stream=file.file,
                user=user,
                enqueue=True,
                source_path=source_path,
            )
            if document.status == "duplicate":
                duplicates += 1
            else:
                uploaded += 1
            results.append(
                BatchUploadItem(
                    document_id=document.id,
                    original_filename=document.original_filename,
                    status=document.status,
                    job_id=job.id if job else None,
                )
            )
        except Exception:
            logger.exception("batch_upload_failed filename=%s", file.filename)
            # ``register_upload`` normally commits one file at a time, but a
            # database error before that commit leaves this shared request
            # session unusable.  Roll it back before advancing to the next
            # selected file so one bad item cannot turn the whole folder into
            # an HTTP 500.
            db.rollback()
            failed += 1

    db.commit()
    return BatchUploadResponse(
        uploaded=uploaded, duplicates=duplicates, failed=failed, documents=results
    )


@router.get("", response_model=list[DocumentRead])
@limiter.limit("120/minute")
def list_documents(
    request: Request,
    status: str | None = None,
    document_type: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Document]:
    stmt = (
        select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc())
    )
    if status:
        stmt = stmt.where(Document.status == status)
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if q:
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Document.original_filename.ilike(f"%{escaped_q}%"))
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.offset(offset).limit(limit)).all())
    # DATA-03: push the scope into SQL so the page slice and the
    # total are both correct for non-admin users. We still run the
    # in-memory ``filter_documents_for_scope`` afterwards because
    # the ``denied_tags`` and ``allowed_document_types`` parts of
    # the scope require per-row metadata inspection that is not
    # worth a dialect-specific JSON expansion in SQL.
    stmt = apply_access_predicates(stmt, scope)
    candidates = list(db.scalars(stmt.offset(offset).limit(limit)).all())
    return filter_documents_for_scope(db, candidates, scope)


@router.post("/reprocess-bulk", response_model=BulkReprocessResponse)
@limiter.limit("10/minute")
def reprocess_bulk(
    request: Request,
    payload: BulkReprocessRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> BulkReprocessResponse:
    try:
        result = bulk_reprocess_documents(
            db,
            filters=BulkReprocessFilters(**payload.model_dump()),
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkReprocessResponse(
        matched=result.matched,
        enqueued=result.enqueued,
        skipped=result.skipped,
        job_ids=result.job_ids,
        mode=result.mode,
    )


@router.post("/reclassify")
@limiter.limit("10/minute")
def reclassify_documents(
    request: Request,
    limit: int = Query(default=500, ge=1, le=5000),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> dict:
    """Reclassify all documents using improved classification rules.

    This re-evaluates document_type without re-running OCR. Useful after
    classification rule changes. Set dry_run=true to preview changes.

    MiniMax M3 (FASE 2):
    * Uses :func:`app.services.classification_v2.classify_multidim` so
      ``source_format``, ``document_subtype``, ``content_tags`` and
      ``classification_evidence`` are recomputed in the same pass.
    * Persists the new ``confidence`` to ``Document.confidence`` (the
      correct mapped attribute) instead of the legacy
      ``classification_confidence`` that did not exist as a column.
    * Tags the run with the classifier version and emits the
      ``track_classification_reclassify`` metric with the
      ``relaunched_ocr``/``relaunched_extraction`` flags always set
      to ``False`` so the operator can confirm the reclassify path
      did not relaunch expensive work.
    """
    from datetime import UTC, datetime

    from app.services.classification import LearnedRule
    from app.services.classification_v2 import classify_multidim
    from app.services.metrics.minimax_m3 import track_classification_reclassify

    # Load learned rules
    learned_rules: list[LearnedRule] = []
    try:
        from app.models.learning import LearnedPattern

        patterns = db.scalars(select(LearnedPattern).where(LearnedPattern.status == "active")).all()
        learned_rules = [
            LearnedRule(
                pattern_value=p.pattern_value,
                target_class=p.target_class,
                confidence=p.confidence,
            )
            for p in patterns
        ]
    except Exception:
        pass

    documents = list(
        db.scalars(select(Document).where(Document.deleted_at.is_(None)).limit(limit)).all()
    )

    changes: list[dict[str, object]] = []
    unchanged = 0
    relaunched_ocr = False
    relaunched_extraction = False

    for doc in documents:
        text = ""
        if hasattr(doc, "pages") and doc.pages:
            text = "\n".join(filter(None, (p.text for p in doc.pages if p.text)))

        result = classify_multidim(
            filename=doc.original_filename,
            source_path=doc.source_path,
            mime_type=doc.mime_type,
            parser_signature=None,
            text=text,
            learned_rules=learned_rules,
        )

        old_type = doc.document_type or "desconocido"
        old_source = doc.source_format
        old_subtype = doc.document_subtype
        if (
            result.document_type != old_type
            or result.source_format != old_source
            or result.document_subtype != old_subtype
            or list(doc.content_tags or []) != list(result.content_tags)
            or doc.classification_evidence != dict(result.evidence)
            or doc.classifier_version != result.classifier_version
        ):
            changes.append(
                {
                    "id": doc.id,
                    "filename": doc.original_filename,
                    "old_type": old_type,
                    "new_type": result.document_type,
                    "old_source_format": old_source,
                    "new_source_format": result.source_format,
                    "old_subtype": old_subtype,
                    "new_subtype": result.document_subtype,
                    "confidence": result.confidence,
                }
            )
            if not dry_run:
                doc.document_type = result.document_type
                doc.source_format = result.source_format
                doc.document_subtype = result.document_subtype
                doc.content_tags = list(result.content_tags)
                doc.classification_evidence = dict(result.evidence)
                doc.classifier_version = result.classifier_version
                doc.classified_at = datetime.now(UTC)
                # Persist the confidence on the mapped column. The
                # previous code wrote to ``classification_confidence``,
                # which is NOT a Document column; the value silently
                # disappeared on commit.
                doc.confidence = result.confidence
        else:
            unchanged += 1

    if not dry_run and changes:
        from app.services.knowledge_version import bump_knowledge_version

        bump_knowledge_version(db, event="documents_reclassified")
        db.commit()

    track_classification_reclassify(
        relaunched_ocr=relaunched_ocr,
        relaunched_extraction=relaunched_extraction,
    )

    return {
        "total": len(documents),
        "changed": len(changes),
        "unchanged": unchanged,
        "relaunched_ocr": relaunched_ocr,
        "relaunched_extraction": relaunched_extraction,
        "changes": changes[:100],
        "dry_run": dry_run,
    }


@router.get("/{document_id}", response_model=DocumentRead)
@limiter.limit("120/minute")
def get_document(
    request: Request,
    document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Document:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{document_id}/pages", response_model=list[DocumentPageRead])
@limiter.limit("120/minute")
def get_document_pages(
    request: Request,
    document_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentPage]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


@router.get("/{document_id}/pages/{page_number}/image")
@limiter.limit("120/minute")
def get_document_page_image(
    request: Request,
    document_id: int,
    page_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .where(DocumentPage.page_number == page_number)
    )
    if not page or not page.image_path:
        raise HTTPException(status_code=404, detail="Page preview not found")
    path = _resolve_stored_image_path(page.image_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Page preview not found")
    # OPS-1: pass ``media_type`` explicitly so the Content-Type
    # header always matches the bytes on disk, regardless of
    # whether the renderer produced JPEG (smaller) or fell
    # back to PNG. The extension on disk and the payload now
    # agree (the parser writes ``.jpg`` when it encoded JPEG,
    # ``.png`` when it fell back), so this is belt-and-braces
    # — the filename inference would also produce the right
    # value, but pinning it here protects against future
    # paths that store previews under non-standard names.
    media_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return FileResponse(path, media_type=media_type)


@router.get("/{document_id}/blocks", response_model=list[DocumentBlockRead])
@limiter.limit("120/minute")
def get_document_blocks(
    request: Request,
    document_id: int,
    page_number: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentBlock]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    stmt = (
        select(DocumentBlock)
        .where(DocumentBlock.document_id == document_id)
        .order_by(DocumentBlock.page_number.asc())
    )
    if page_number:
        stmt = stmt.where(DocumentBlock.page_number == page_number)
    return list(db.scalars(stmt.offset(offset).limit(limit)).all())


def _relation_row_to_read(row: RelationRow) -> GraphRelationRead:
    """Translate the service dataclass into the API schema."""
    return GraphRelationRead(
        relation_id=row.relation_id,
        relation_type=row.relation_type,
        polarity=row.polarity,
        confidence=row.confidence,
        status=row.status,
        source_entity_id=row.source_entity_id,
        source_entity_type=row.source_entity_type,
        source_entity_value=row.source_entity_value,
        target_entity_id=row.target_entity_id,
        target_entity_type=row.target_entity_type,
        target_entity_value=row.target_entity_value,
        evidence=[
            GraphRelationEvidenceRead(
                evidence_id=item.evidence_id,
                relation_id=item.relation_id,
                document_id=item.document_id,
                page_number=item.page_number,
                quote=item.quote,
                confidence=item.confidence,
                extractor_version=item.extractor_version,
                created_at=item.created_at,
            )
            for item in row.evidence
        ],
    )


@router.get(
    "/{document_id}/graph-relations",
    response_model=DocumentGraphRelationsResponse,
)
@limiter.limit("60/minute")
def get_document_graph_relations(
    request: Request,
    document_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentGraphRelationsResponse:
    """Return the relational graph that touches ``document_id``.

    The traversal is two-hop: the document's entity mentions, then
    every relation whose source or target is one of those entities.
    Each relation comes with the verbatim evidence quotes that
    back it (``graph_relation_evidence.quote``) so the UI can
    render a fully-auditable citation. The response is the
    read-only counterpart of the write path in
    ``app.services.graph_extraction``.
    """
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    rows = list_relations_for_document(db, document_id, limit=limit)
    return DocumentGraphRelationsResponse(
        document_id=document_id,
        relations=[_relation_row_to_read(row) for row in rows],
    )


@router.get(
    "/{document_id}/graph-evidence",
    response_model=list[GraphRelationEvidenceRead],
)
@limiter.limit("60/minute")
def get_document_graph_evidence(
    request: Request,
    document_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GraphRelationEvidenceRead]:
    """Return only the evidence quotes that originate in ``document_id``.

    This is the lightweight surface the chat agent uses to
    surface audit-trail citations without exposing the full
    relation graph. The endpoint honours the same access scope
    as the rest of the document routes.
    """
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    rows = list_evidence_quotes(db, document_id, limit=limit)
    return [
        GraphRelationEvidenceRead(
            evidence_id=item.evidence_id,
            relation_id=item.relation_id,
            document_id=item.document_id,
            page_number=item.page_number,
            quote=item.quote,
            confidence=item.confidence,
            extractor_version=item.extractor_version,
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.get("/{document_id}/entities", response_model=list[DocumentEntityRead])
@limiter.limit("120/minute")
def get_document_entities(
    request: Request,
    document_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentEntity]:
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return list(
        db.scalars(
            select(DocumentEntity)
            .where(DocumentEntity.document_id == document_id)
            .order_by(DocumentEntity.entity_type.asc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


@router.post("/{document_id}/reprocess", response_model=ExtractionJobRead)
@limiter.limit("10/minute")
def reprocess(
    request: Request,
    document_id: int,
    mode: Literal[
        "full", "ocr", "text", "classification", "entities", "chunks", "embeddings"
    ] = Query(default="full"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    document = db.get(Document, document_id)
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    job_type = "reprocess" if mode == "full" else f"reprocess:{mode}"
    job = reprocess_document(db, document=document, user=user, job_type=job_type)
    return job


@router.delete("/{document_id}", response_model=DocumentRead)
@limiter.limit("30/minute")
def delete_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> Document:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_access_document(db, document, resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Document not found")
    return soft_delete_document(db, document=document, user=user)


@router.get("/{document_id}/download")
@limiter.limit("30/minute")
def download_document(
    request: Request,
    document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    document = db.get(Document, document_id)
    if (
        not can_access_document(db, document, resolve_user_access_scope(db, user))
        or not document.stored_filename
    ):
        raise HTTPException(status_code=404, detail="Document not found")
    path = (settings.files_dir / document.stored_filename).resolve()
    if not path.exists() or settings.files_dir.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Stored file not found")
    write_audit(
        db, user=user, action="document_downloaded", entity_type="document", entity_id=document.id
    )
    db.commit()
    return FileResponse(
        path,
        filename=document.original_filename,
        media_type=document.mime_type or "application/octet-stream",
    )


def _resolve_files_dir_path(stored_path: str) -> Path:
    root = settings.files_dir.resolve()
    candidate = Path(stored_path)
    path = candidate.resolve() if candidate.is_absolute() else (root / stored_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Stored file not found") from None
    if path.is_symlink():
        raise HTTPException(status_code=404, detail="Stored file not found")
    return path


# When the stored path is missing on disk (e.g. a reprocess rewrote the
# page preview as ``.jpg`` but the ``DocumentPage.image_path`` column still
# points at the old ``.png``), fall back to the sibling file with the other
# common raster extension so the viewer still renders the page. Symlinks and
# paths escaping ``files_dir`` are rejected either way.
_IMAGE_EXT_FALLBACKS = {".png": [".jpg", ".jpeg"], ".jpg": [".png"], ".jpeg": [".png"]}


def _resolve_stored_image_path(stored_path: str) -> Path | None:
    primary = _resolve_files_dir_path(stored_path)
    if primary.is_file():
        return primary
    stem = primary.with_suffix("")
    for ext in _IMAGE_EXT_FALLBACKS.get(primary.suffix.lower(), []):
        candidate = stem.with_suffix(ext)
        try:
            candidate.relative_to(settings.files_dir.resolve())
        except ValueError:
            continue
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None
