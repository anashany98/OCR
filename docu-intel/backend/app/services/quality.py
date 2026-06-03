from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Document, DocumentPage, Order, Plan


LOW_OCR_THRESHOLD = 0.70
MIN_TEXT_CHARS = 40


@dataclass(frozen=True)
class QualityResult:
    status: str
    score: float
    flags: list[str]

    @property
    def needs_review(self) -> bool:
        return self.status in {"processed_low_quality", "processed_missing_fields", "needs_human_review", "failed"}


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

    if low_ocr_confidences:
        flags.add("low_ocr_confidence")

    if document.document_type in {"desconocido", "", None}:
        flags.add("document_type_unknown")

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
        flags.add("invoice_date_missing")
    elif document.document_type == "plano":
        plan = db.scalar(select(Plan).where(Plan.document_id == document.id).limit(1))
        if not plan or not plan.has_valid_scale:
            flags.add("plan_without_valid_scale")

    score = _quality_score(db, document, flags)
    if document.status == "failed":
        status = "failed"
    elif "page_failed" in flags:
        status = "needs_human_review"
    elif "low_ocr_confidence" in flags or "page_without_text" in flags or score < 0.70:
        status = "processed_low_quality"
    elif any(flag.endswith("_missing") or flag in {"budget_number_missing", "order_number_missing", "supplier_missing", "invoice_date_missing"} for flag in flags):
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
    db.flush()


def refresh_quality_from_existing_pages(db: Session, document: Document) -> QualityResult:
    pages = list(db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all())
    text = "\n\n".join(page.text or "" for page in pages)
    low = [page.ocr_confidence for page in pages if page.ocr_confidence is not None and page.ocr_confidence < LOW_OCR_THRESHOLD]
    result = evaluate_document_quality(db, document, text=text, page_count=len(pages), low_ocr_confidences=low)
    update_document_quality(db, document, result)
    return result


def _quality_score(db: Session, document: Document, flags: set[str]) -> float:
    pages = list(db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all())
    ocr_values = [page.ocr_confidence for page in pages if page.ocr_confidence is not None]
    base = document.confidence if document.confidence is not None else 0.80
    if ocr_values:
        base = (base + sum(ocr_values) / len(ocr_values)) / 2
    penalty = min(0.55, len(flags) * 0.08)
    return round(max(0.0, min(1.0, base - penalty)), 4)
