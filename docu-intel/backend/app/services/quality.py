from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Budget, Document, DocumentPage, Order, Plan
from app.services.dates import find_dates_in_text

LOW_OCR_THRESHOLD = settings.low_ocr_confidence_threshold
MIN_TEXT_CHARS = 40


@dataclass(frozen=True)
class QualityResult:
    status: str
    score: float
    flags: list[str]

    @property
    def needs_review(self) -> bool:
        return self.status in {
            "processed_low_quality",
            "processed_missing_fields",
            "needs_human_review",
            "failed",
        }


def evaluate_document_quality(
    db: Session,
    document: Document,
    *,
    text: str | None,
    page_count: int | None,
    low_ocr_confidences: list[float] | None = None,
    business_needs_review: bool = False,
    plan_needs_review: bool = False,
) -> QualityResult:
    flags: set[str] = set()
    clean_text = (text or "").strip()

    if not clean_text:
        flags.add("page_without_text")
    elif len(clean_text) < MIN_TEXT_CHARS:
        flags.add("text_too_short")

    if page_count == 0:
        flags.add("page_without_text")

    failed_page_id = db.scalar(
        select(DocumentPage.id)
        .where(DocumentPage.document_id == document.id)
        .where(DocumentPage.page_status == "failed")
        .limit(1)
    )
    if failed_page_id is not None:
        flags.add("page_failed")

    low_ocr_count = len(low_ocr_confidences or [])
    low_ocr_ratio = low_ocr_count / max(int(page_count or low_ocr_count or 1), 1)
    if low_ocr_count and (page_count in {None, 0, 1} or low_ocr_ratio >= 0.50):
        flags.add("low_ocr_confidence")
    elif low_ocr_count:
        flags.add("partial_low_ocr_confidence")

    if document.document_type in {"desconocido", "", None}:
        flags.add("document_type_unknown")

    # --- Fotos de producto: no penalizar la ausencia de texto ---
    # Las fotos detectadas por el content_router (interior_design /
    # fabric_description) skipean el OCR a propósito (ocr_engine="photo_skip").
    # Sin este exento, todas las fotos válidas van a needs_review por
    # "page_without_text" + "low_ocr_confidence", cuando son correctas.
    is_photo_doc = document.document_type in {
        "foto_producto", "muestra_tela", "croquis_medida"
    }
    if is_photo_doc:
        # Consultar si TODAS las páginas son photo_skip (foto pura, sin OCR)
        total_pages = db.scalar(
            select(func.count(DocumentPage.id))
            .where(DocumentPage.document_id == document.id)
        ) or 0
        photo_skip_pages = db.scalar(
            select(func.count(DocumentPage.id))
            .where(DocumentPage.document_id == document.id)
            .where(DocumentPage.ocr_engine == "photo_skip")
        ) or 0
        if total_pages > 0 and photo_skip_pages == total_pages:
            flags.discard("page_without_text")
            flags.discard("low_ocr_confidence")
            flags.discard("partial_low_ocr_confidence")
            flags.discard("text_too_short")

    if business_needs_review:
        flags.add("business_extraction_needs_review")
    if plan_needs_review:
        flags.add("plan_extraction_needs_review")

    if document.document_type == "presupuesto":
        budget = db.scalar(select(Budget).where(Budget.document_id == document.id).limit(1))
        if not budget or not budget.budget_number:
            flags.add("budget_number_missing")
    elif document.document_type == "pedido":
        order = db.scalar(select(Order).where(Order.document_id == document.id).limit(1))
        if not order or not order.order_number:
            flags.add("order_number_missing")
        if not order or not order.supplier_name:
            flags.add("supplier_missing")
    elif document.document_type == "factura":
        # Only flag missing date if the text has no recognisable date at all.
        if not find_dates_in_text(clean_text):
            flags.add("invoice_date_missing")
    elif document.document_type == "plano":
        plan = db.scalar(select(Plan).where(Plan.document_id == document.id).limit(1))
        if not plan or not plan.has_valid_scale:
            flags.add("plan_without_valid_scale")

    score = _quality_score(db, document, flags)
    pages = list(
        db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all()
    )
    ocr_values = [page.ocr_confidence for page in pages if page.ocr_confidence is not None]
    min_ocr = min(ocr_values) if ocr_values else 0.0
    classification_conf = document.confidence if document.confidence is not None else 0.0
    is_classified = document.document_type not in {"desconocido", "", None}

    # Trust shortcut: high-confidence extraction → auto-approve, even with some
    # missing structured fields. The audit log keeps a record for rollback.
    #
    # Digital PDFs (min_ocr == 1.0) get a relaxed path: text comes straight
    # from the PDF content stream, so it is always readable.  Business
    # extraction may fail to match its regex patterns (missing fields), but
    # that is a pattern-gap issue, not a quality issue — the document
    # should still be auto-approved if the text is present and classified.
    is_digital = min_ocr >= 1.0

    # Quick auto-approve for emails and well-classified documents.
    # Emails (.msg) are always useful as-is; classified docs with
    # some text should not block on missing structured fields.
    has_text = any(
        (page.text or "").strip()
        for page in pages
    )
    is_email = document.document_type == "email_exportado"
    well_classified = is_classified and classification_conf >= 0.6
    if (
        document.status != "failed"
        and "page_failed" not in flags
        and (has_text or is_photo_doc)   # --- CAMBIO: fotos sin texto también ---
        and (is_email or well_classified or is_photo_doc)  # --- CAMBIO ---
    ):
        status = "processed_ok"
    if (
        document.status != "failed"
        and "page_failed" not in flags
        and "page_without_text" not in flags
        and min_ocr >= settings.auto_approve_min_ocr
        and (
            is_digital
            or classification_conf >= settings.auto_approve_min_classification
        )
        and is_classified
        and (
            settings.auto_approve_allow_missing_fields
            or not any(f.endswith("_missing") for f in flags)
        )
    ):
        status = "processed_ok"
    elif document.status == "failed":
        status = "failed"
    elif "page_failed" in flags:
        status = "needs_human_review"
    elif (
        "low_ocr_confidence" in flags
        or "page_without_text" in flags
        or score < settings.quality_score_threshold
    ):
        status = "processed_low_quality"
    elif any(
        flag.endswith("_missing")
        or flag
        in {
            "budget_number_missing",
            "order_number_missing",
            "supplier_missing",
            "invoice_date_missing",
        }
        for flag in flags
    ):
        # Accept partial extraction: if at least one key field was
        # found (budget_number OR supplier_name), don't block on
        # missing fields. Only flag when ALL key fields are missing.
        from app.models import DocumentEntity
        existing_entities = list(
            db.scalars(
                select(DocumentEntity).where(DocumentEntity.document_id == document.id)
            ).all()
        )
        has_any_key_field = any(
            e.entity_type in {"budget_number", "supplier_name", "order_number", "invoice_number"}
            for e in existing_entities
        )
        if has_any_key_field:
            status = "processed_ok"
        else:
            status = "processed_missing_fields"
    elif business_needs_review or plan_needs_review or "document_type_unknown" in flags:
        status = "needs_human_review"
    else:
        status = "processed_ok"

    return QualityResult(status=status, score=score, flags=sorted(flags))


def update_document_quality(db: Session, document: Document, result: QualityResult) -> None:
    document.quality_status = result.status
    document.quality_score = result.score
    document.quality_flags_json = result.flags
    # Keep document.status consistent with the quality verdict. If the new
    # quality says processed_ok and the document was sitting in needs_review,
    # promote it. This keeps the document list and the quality dashboard in
    # sync without forcing the user to re-process.
    if result.status == "processed_ok" and document.status in {
        "needs_review",
        "pending",
        "processing",
    }:
        document.status = "processed"
    elif result.status == "failed" and document.status not in {"failed"}:
        document.status = "failed"
    db.flush()


def refresh_quality_from_existing_pages(db: Session, document: Document) -> QualityResult:
    pages = list(
        db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all()
    )
    text = "\n\n".join(page.text or "" for page in pages)
    low = [
        page.ocr_confidence
        for page in pages
        if page.ocr_confidence is not None and page.ocr_confidence < LOW_OCR_THRESHOLD
    ]
    result = evaluate_document_quality(
        db, document, text=text, page_count=len(pages), low_ocr_confidences=low
    )
    update_document_quality(db, document, result)
    return result


def _quality_score(db: Session, document: Document, flags: set[str]) -> float:
    pages = list(
        db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all()
    )
    ocr_values = [page.ocr_confidence for page in pages if page.ocr_confidence is not None]
    base = document.confidence if document.confidence is not None else 0.80
    if ocr_values:
        # Use minimum OCR confidence instead of average.
        # A single bad page should penalize the whole document,
        # not be diluted by many good pages.
        min_ocr = min(ocr_values)
        base = (base + min_ocr) / 2
    penalty = min(0.55, len(flags) * settings.quality_flag_penalty)
    return round(max(0.0, min(1.0, base - penalty)), 4)
