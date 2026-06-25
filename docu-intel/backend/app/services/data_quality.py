from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, Document, DocumentPage, Order, Plan, SensitiveTag
from app.services.quality import LOW_OCR_THRESHOLD, refresh_quality_from_existing_pages

RULE_DEFINITIONS = {
    "ocr_low": "Paginas con OCR por debajo del umbral operativo.",
    "page_without_text": "Documentos sin texto extraido.",
    "document_type_unknown": "Documentos sin clasificacion fiable.",
    "missing_budget_number": "Presupuestos sin numero estructurado.",
    "missing_order_supplier": "Pedidos sin proveedor.",
    "missing_invoice_date": "Facturas sin fecha estructurada.",
    "plan_without_scale": "Planos sin escala valida.",
    "duplicate_document": "Documentos marcados como duplicados.",
    "failed_processing": "Documentos o jobs fallidos.",
}


@dataclass(frozen=True)
class QualityRecalculateResult:
    matched: int
    updated: int
    needs_review: int


def quality_rules_payload(db: Session) -> dict:
    tags = db.scalars(
        select(SensitiveTag)
        .where(SensitiveTag.is_active.is_(True))
        .order_by(SensitiveTag.name.asc())
    ).all()
    return {
        "low_ocr_threshold": LOW_OCR_THRESHOLD,
        "sensitive_tags": [tag.name for tag in tags],
        "business_rules": sorted(RULE_DEFINITIONS),
        "descriptions": RULE_DEFINITIONS,
    }


def quality_summary(db: Session) -> dict:
    rules = {
        key: {"count": 0, "description": description}
        for key, description in RULE_DEFINITIONS.items()
    }
    rules["ocr_low"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .join(Document, Document.id == DocumentPage.document_id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentPage.ocr_confidence.is_not(None))
            .where(DocumentPage.ocr_confidence < LOW_OCR_THRESHOLD)
        )
        or 0
    )
    rules["page_without_text"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .outerjoin(DocumentPage, DocumentPage.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(
                (DocumentPage.id.is_(None))
                | (DocumentPage.text.is_(None))
                | (DocumentPage.text == "")
            )
        )
        or 0
    )
    rules["document_type_unknown"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_(None), Document.document_type == "desconocido")
        )
        or 0
    )
    rules["missing_budget_number"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .outerjoin(Budget, Budget.document_id == Document.id)
            .where(Document.deleted_at.is_(None), Document.document_type == "presupuesto")
            .where(
                (Budget.id.is_(None))
                | (Budget.budget_number.is_(None))
                | (Budget.budget_number == "")
            )
        )
        or 0
    )
    rules["missing_order_supplier"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .outerjoin(Order, Order.document_id == Document.id)
            .where(Document.deleted_at.is_(None), Document.document_type == "pedido")
            .where(
                (Order.id.is_(None)) | (Order.supplier_name.is_(None)) | (Order.supplier_name == "")
            )
        )
        or 0
    )
    rules["missing_invoice_date"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_(None), Document.document_type == "factura")
        )
        or 0
    )
    rules["plan_without_scale"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .outerjoin(Plan, Plan.document_id == Document.id)
            .where(Document.deleted_at.is_(None), Document.document_type == "plano")
            .where((Plan.id.is_(None)) | (Plan.has_valid_scale.is_(False)))
        )
        or 0
    )
    rules["duplicate_document"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_(None), Document.status == "duplicate")
        )
        or 0
    )
    rules["failed_processing"]["count"] = int(
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_(None), Document.status == "failed")
        )
        or 0
    )
    by_status = {
        status: count
        for status, count in db.execute(
            select(Document.quality_status, func.count())
            .where(Document.deleted_at.is_(None))
            .group_by(Document.quality_status)
        ).all()
    }
    return {"rules": rules, "by_quality_status": by_status}


def recalculate_quality(db: Session, *, limit: int = 500) -> QualityRecalculateResult:
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
            .limit(limit)
        ).all()
    )
    updated = 0
    needs_review = 0
    for document in documents:
        result = refresh_quality_from_existing_pages(db, document)
        updated += 1
        if result.needs_review:
            needs_review += 1
    db.flush()
    return QualityRecalculateResult(
        matched=len(documents), updated=updated, needs_review=needs_review
    )
