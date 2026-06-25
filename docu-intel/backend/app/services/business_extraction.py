from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    BudgetLine,
    Document,
    DocumentEntity,
    Invoice,
    Order,
    OrderLine,
)
from app.parsers.types import ExtractedPage
from app.services.dates import first_date_in_text, parse_spanish_date

logger = logging.getLogger(__name__)


@dataclass
class ExtractedLine:
    reference: str | None
    description: str | None
    quantity: float | None
    unit: str | None
    unit_price: float | None
    total_price: float | None
    confidence: float


@dataclass
class BudgetExtraction:
    document_id: int
    budget_number: str | None
    client_name: str | None
    date: date | None
    total_amount: float | None
    currency: str | None
    status: str | None
    accepted_detected: bool
    confidence: float
    lines: list[ExtractedLine] = field(default_factory=list)


@dataclass
class OrderExtraction:
    document_id: int
    order_number: str | None
    supplier_name: str | None
    client_name: str | None
    date: date | None
    total_amount: float | None
    currency: str | None
    related_budget_number: str | None
    confidence: float
    lines: list[ExtractedLine] = field(default_factory=list)


@dataclass
class InvoiceExtraction:
    document_id: int
    invoice_number: str | None
    supplier_name: str | None
    supplier_tax_id: str | None
    client_name: str | None
    date: date | None
    taxable_base: float | None
    vat_amount: float | None
    total_amount: float | None
    currency: str | None
    related_order_number: str | None
    confidence: float


@dataclass
class ValidationIssue:
    """A concrete reason a business extraction needs human review.

    ``field`` is the logical field that failed the check
    (``"line_total"``, ``"subtotal"``, ``"total"``). ``expected`` and
    ``actual`` carry the values so the admin UI can render a useful
    diff without re-running the extractor.
    """

    check: str
    field: str
    expected: float | None
    actual: float | None
    detail: str | None = None


@dataclass
class PersistedBusinessExtraction:
    budget: Budget | None = None
    order: Order | None = None
    invoice: Invoice | None = None
    needs_review: bool = False
    # Concrete reasons behind ``needs_review`` so the admin UI can
    # show *why* the document needs attention instead of a bare flag.
    review_reasons: list[str] = field(default_factory=list)
    validation_issues: list[ValidationIssue] = field(default_factory=list)


def extract_budget(
    document_id: int,
    text: str,
    document_confidence: float | None,
    pages: list[ExtractedPage] | None = None,
) -> BudgetExtraction | None:
    if not text.strip():
        return None

    budget_number = _first_match(
        text,
        [
            r"\bpresupuesto\s*(?:n[ºo]\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
            r"\boferta\s*(?:n[ºo]\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
            r"\bn[ºo]\s*presupuesto\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
        ],
    )
    client_name = _line_value(text, ["cliente", "razon social", "razón social"])
    parsed_date = _date_from_label(text, ["fecha", "fecha presupuesto"])
    total_amount, currency = _total_amount(text, "presupuesto")
    status = _status(text)
    accepted_detected = status == "aceptado"
    lines = _extract_lines_for_document(text, pages)

    score = _confidence(
        document_confidence, [budget_number, client_name, parsed_date, total_amount], bool(lines)
    )
    return BudgetExtraction(
        document_id=document_id,
        budget_number=budget_number,
        client_name=client_name,
        date=parsed_date,
        total_amount=total_amount,
        currency=currency,
        status=status,
        accepted_detected=accepted_detected,
        confidence=score,
        lines=lines,
    )


def extract_order(
    document_id: int,
    text: str,
    document_confidence: float | None,
    pages: list[ExtractedPage] | None = None,
) -> OrderExtraction | None:
    if not text.strip():
        return None

    order_number = _first_match(
        text,
        [
            r"\bpedido\s*(?:n[ºo]\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
            r"\borden\s+de\s+compra\s*(?:n[ºo]\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
            r"\bn[ºo]\s*pedido\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
        ],
    )
    supplier_name = _line_value(text, ["proveedor", "suministrador"])
    client_name = _line_value(text, ["cliente"])
    parsed_date = _date_from_label(text, ["fecha pedido", "fecha"])
    total_amount, currency = _total_amount(text, "pedido")
    related_budget_number = _line_value(
        text, ["presupuesto relacionado", "presupuesto ref", "presupuesto"]
    )
    if related_budget_number:
        related_budget_number = related_budget_number.split()[0].strip(" .,:;")
    lines = _extract_lines_for_document(text, pages)

    score = _confidence(
        document_confidence, [order_number, supplier_name, parsed_date, total_amount], bool(lines)
    )
    return OrderExtraction(
        document_id=document_id,
        order_number=order_number,
        supplier_name=supplier_name,
        client_name=client_name,
        date=parsed_date,
        total_amount=total_amount,
        currency=currency,
        related_budget_number=related_budget_number,
        confidence=score,
        lines=lines,
    )


def extract_invoice(
    document_id: int, text: str, document_confidence: float | None
) -> InvoiceExtraction | None:
    if not text.strip():
        return None

    invoice_number = _first_match(
        text,
        [
            r"\bfactura\s*(?:n[ºo]\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./-]{1,})",
            r"\bn[ºo]\s*factura\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{1,})",
        ],
    )
    supplier_name = _line_value(
        text, ["proveedor", "emisor", "empresa", "razon social", "razón social"]
    )
    supplier_tax_id = _tax_id(text)
    client_name = _line_value(text, ["cliente", "receptor"])
    parsed_date = _date_from_label(text, ["fecha factura", "fecha"])
    taxable_base, base_currency = _amount_from_label(text, ["base imponible", "base"])
    vat_amount, vat_currency = _amount_from_label(text, ["iva", "importe iva"])
    total_amount, total_currency = _total_amount(text, "factura")
    related_order_number = _line_value(text, ["pedido relacionado", "pedido", "orden de compra"])
    if related_order_number:
        related_order_number = related_order_number.split()[0].strip(" .,:;")
    currency = total_currency or base_currency or vat_currency

    score = _confidence(
        document_confidence,
        [
            invoice_number,
            supplier_name,
            supplier_tax_id,
            parsed_date,
            taxable_base,
            vat_amount,
            total_amount,
        ],
        False,
    )
    return InvoiceExtraction(
        document_id=document_id,
        invoice_number=invoice_number,
        supplier_name=supplier_name,
        supplier_tax_id=supplier_tax_id,
        client_name=client_name,
        date=parsed_date,
        taxable_base=taxable_base,
        vat_amount=vat_amount,
        total_amount=total_amount,
        currency=currency,
        related_order_number=related_order_number,
        confidence=score,
    )


def persist_business_extraction(
    db: Session,
    document: Document,
    text: str,
    pages: list[ExtractedPage] | None = None,
) -> PersistedBusinessExtraction:
    _delete_existing_business_data(db, document.id)

    if document.document_type == "presupuesto":
        extraction = extract_budget(document.id, text, document.confidence, pages=pages)
        if not extraction:
            return PersistedBusinessExtraction(
                needs_review=True,
                review_reasons=["sin_extraccion"],
            )
        budget = Budget(
            document_id=document.id,
            budget_number=extraction.budget_number,
            budget_number_normalized=_normalize_doc_number(extraction.budget_number)
            if extraction.budget_number
            else None,
            client_name=extraction.client_name,
            date=extraction.date,
            total_amount=extraction.total_amount,
            currency=extraction.currency,
            status=extraction.status,
            accepted_detected=extraction.accepted_detected,
            confidence=extraction.confidence,
        )
        db.add(budget)
        db.flush()
        for line in extraction.lines:
            db.add(
                BudgetLine(
                    budget_id=budget.id,
                    reference=line.reference,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=line.unit_price,
                    total_price=line.total_price,
                    confidence=line.confidence,
                )
            )
        _add_entities_for_budget(db, document.id, extraction)
        issues = _validate_extraction(extraction)
        needs_review = _budget_needs_review(extraction) or bool(issues)
        return PersistedBusinessExtraction(
            budget=budget,
            needs_review=needs_review,
            review_reasons=_issues_to_reasons(issues),
            validation_issues=issues,
        )

    if document.document_type == "pedido":
        extraction = extract_order(document.id, text, document.confidence, pages=pages)
        if not extraction:
            return PersistedBusinessExtraction(
                needs_review=True,
                review_reasons=["sin_extraccion"],
            )
        if extraction.date is None:
            _add_entities_for_order(db, document.id, extraction)
            return PersistedBusinessExtraction(
                needs_review=True,
                review_reasons=["falta_fecha"],
            )
        related_budget_id = _find_related_budget_id(db, extraction)
        order = Order(
            document_id=document.id,
            order_number=extraction.order_number,
            order_number_normalized=_normalize_doc_number(extraction.order_number)
            if extraction.order_number
            else None,
            supplier_name=extraction.supplier_name,
            client_name=extraction.client_name,
            date=extraction.date,
            total_amount=extraction.total_amount,
            currency=extraction.currency,
            related_budget_id=related_budget_id,
            confidence=extraction.confidence,
        )
        db.add(order)
        db.flush()
        for line in extraction.lines:
            db.add(
                OrderLine(
                    order_id=order.id,
                    reference=line.reference,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=line.unit_price,
                    total_price=line.total_price,
                    confidence=line.confidence,
                )
            )
        _add_entities_for_order(db, document.id, extraction)
        issues = _validate_extraction(extraction)
        needs_review = _order_needs_review(extraction, related_budget_id) or bool(issues)
        return PersistedBusinessExtraction(
            order=order,
            needs_review=needs_review,
            review_reasons=_issues_to_reasons(issues),
            validation_issues=issues,
        )

    if document.document_type == "factura":
        extraction = extract_invoice(document.id, text, document.confidence)
        if not extraction:
            return PersistedBusinessExtraction(
                needs_review=True,
                review_reasons=["sin_extraccion"],
            )
        related_order_id = _find_related_order_id(db, extraction)
        invoice = Invoice(
            document_id=document.id,
            invoice_number=extraction.invoice_number,
            supplier_name=extraction.supplier_name,
            client_name=extraction.client_name,
            date=extraction.date,
            total_amount=extraction.total_amount,
            currency=extraction.currency,
            related_order_id=related_order_id,
            confidence=extraction.confidence,
        )
        db.add(invoice)
        db.flush()
        _add_entities_for_invoice(db, document.id, extraction)
        issues = _validate_extraction(extraction)
        needs_review = _invoice_needs_review(extraction) or bool(issues)
        return PersistedBusinessExtraction(
            invoice=invoice,
            needs_review=needs_review,
            review_reasons=_issues_to_reasons(issues),
            validation_issues=issues,
        )

    return PersistedBusinessExtraction()


def _delete_existing_business_data(db: Session, document_id: int) -> None:
    budget_ids = list(db.scalars(select(Budget.id).where(Budget.document_id == document_id)).all())
    order_ids = list(db.scalars(select(Order.id).where(Order.document_id == document_id)).all())
    invoice_ids = list(
        db.scalars(select(Invoice.id).where(Invoice.document_id == document_id)).all()
    )
    if budget_ids:
        db.execute(delete(BudgetLine).where(BudgetLine.budget_id.in_(budget_ids)))
        db.execute(delete(Order).where(Order.related_budget_id.in_(budget_ids)))
        db.execute(delete(Budget).where(Budget.id.in_(budget_ids)))
    if order_ids:
        db.execute(delete(OrderLine).where(OrderLine.order_id.in_(order_ids)))
        db.execute(delete(Order).where(Order.id.in_(order_ids)))
    if invoice_ids:
        db.execute(delete(Invoice).where(Invoice.id.in_(invoice_ids)))
    db.execute(delete(DocumentEntity).where(DocumentEntity.document_id == document_id))
    db.flush()


def _add_entities_for_budget(db: Session, document_id: int, extraction: BudgetExtraction) -> None:
    _entity(db, document_id, "budget_number", extraction.budget_number, extraction.confidence)
    _entity(db, document_id, "client_name", extraction.client_name, extraction.confidence)
    _entity(
        db,
        document_id,
        "total_amount",
        _amount_text(extraction.total_amount),
        extraction.confidence,
    )
    for line in extraction.lines:
        _entity(db, document_id, "reference", line.reference, line.confidence)


def _add_entities_for_order(db: Session, document_id: int, extraction: OrderExtraction) -> None:
    _entity(db, document_id, "order_number", extraction.order_number, extraction.confidence)
    _entity(db, document_id, "supplier_name", extraction.supplier_name, extraction.confidence)
    _entity(db, document_id, "client_name", extraction.client_name, extraction.confidence)
    _entity(
        db,
        document_id,
        "related_budget_number",
        extraction.related_budget_number,
        extraction.confidence,
    )
    _entity(
        db,
        document_id,
        "total_amount",
        _amount_text(extraction.total_amount),
        extraction.confidence,
    )
    for line in extraction.lines:
        _entity(db, document_id, "reference", line.reference, line.confidence)


def _add_entities_for_invoice(db: Session, document_id: int, extraction: InvoiceExtraction) -> None:
    _entity(db, document_id, "invoice_number", extraction.invoice_number, extraction.confidence)
    _entity(db, document_id, "supplier_name", extraction.supplier_name, extraction.confidence)
    _entity(db, document_id, "supplier_tax_id", extraction.supplier_tax_id, extraction.confidence)
    _entity(db, document_id, "client_name", extraction.client_name, extraction.confidence)
    _entity(
        db,
        document_id,
        "invoice_date",
        extraction.date.isoformat() if extraction.date else None,
        extraction.confidence,
    )
    _entity(
        db,
        document_id,
        "taxable_base",
        _amount_text(extraction.taxable_base),
        extraction.confidence,
    )
    _entity(
        db, document_id, "vat_amount", _amount_text(extraction.vat_amount), extraction.confidence
    )
    _entity(
        db,
        document_id,
        "total_amount",
        _amount_text(extraction.total_amount),
        extraction.confidence,
    )
    _entity(
        db,
        document_id,
        "related_order_number",
        extraction.related_order_number,
        extraction.confidence,
    )


def _entity(
    db: Session, document_id: int, entity_type: str, value: str | None, confidence: float
) -> None:
    if not value:
        return
    db.add(
        DocumentEntity(
            document_id=document_id,
            entity_type=entity_type,
            entity_value=value,
            normalized_value=value.lower(),
            confidence=confidence,
        )
    )


def _normalize_doc_number(value: str | None) -> str:
    """Normalise a document number for fuzzy comparison.

    Strips whitespace, hyphens, dots, slashes and surrounding noise so
    that ``"2026/143"``, ``"2026-143"``, ``" 2026/143 "`` and
    ``"2026 143"`` collapse to the same canonical form. Lower-cased
    because budget numbers are case-insensitive in practice.

    BE-LOOKUP-1 (Sprint 2): the same normalization is stored on the
    model (``Budget.budget_number_normalized`` /
    ``Order.order_number_normalized``) so the related-document
    resolution can do an indexed SELECT instead of loading N rows
    into Python. The function is kept for callers that need a
    one-off normalization of a free-text value.
    """
    if not value:
        return ""
    return re.sub(r"[\s\-./]", "", value).lower()


def _find_related_budget_id(db: Session, extraction: OrderExtraction) -> int | None:
    """Resolve the related budget for an order extraction.

    BE-LOOKUP-1 (Sprint 2): the previous implementation loaded up
    to 500 budgets into Python and compared normalised forms in a
    loop. The new path uses the ``budget_number_normalized`` column
    for an indexed SQL lookup. Fallback to the Python loop only
    when the normalized column has not been backfilled yet (pre-migration
    rows).
    """
    needle_raw = extraction.related_budget_number
    if not needle_raw:
        return None
    needle = _normalize_doc_number(needle_raw)
    if not needle:
        return None
    # 1. Exact match (indexed, O(1)).
    budget = db.scalar(select(Budget).where(Budget.budget_number == needle_raw).limit(1))
    if budget:
        return budget.id
    # 2. Normalized match via the indexed column (O(1)).
    budget = db.scalar(select(Budget).where(Budget.budget_number_normalized == needle).limit(1))
    if budget:
        return budget.id
    # 3. Fallback: Python loop for pre-migration rows that have
    #    no normalized column populated. This is the legacy path
    #    and will be removed in a future release.
    for candidate in db.scalars(select(Budget).order_by(Budget.id.desc()).limit(500)).all():
        if _normalize_doc_number(candidate.budget_number) == needle:
            return candidate.id
    return None


def _find_related_order_id(db: Session, extraction: InvoiceExtraction) -> int | None:
    """Resolve the related order for an invoice extraction.

    Same design as :func:`_find_related_budget_id`.
    """
    needle_raw = extraction.related_order_number
    if not needle_raw:
        return None
    needle = _normalize_doc_number(needle_raw)
    if not needle:
        return None
    # 1. Exact match (indexed, O(1)).
    order = db.scalar(select(Order).where(Order.order_number == needle_raw).limit(1))
    if order:
        return order.id
    # 2. Normalized match via the indexed column (O(1)).
    order = db.scalar(select(Order).where(Order.order_number_normalized == needle).limit(1))
    if order:
        return order.id
    # 3. Fallback: Python loop for pre-migration rows.
    for candidate in db.scalars(select(Order).order_by(Order.id.desc()).limit(500)).all():
        if _normalize_doc_number(candidate.order_number) == needle:
            return candidate.id
    return None


def _budget_needs_review(extraction: BudgetExtraction) -> bool:
    return (
        extraction.confidence < 0.65 or not extraction.budget_number or not extraction.total_amount
    )


def _order_needs_review(extraction: OrderExtraction, related_budget_id: int | None) -> bool:
    relation_was_expected = bool(extraction.related_budget_number)
    return (
        extraction.confidence < 0.65
        or not extraction.order_number
        or not extraction.total_amount
        or (relation_was_expected and related_budget_id is None)
    )


def _invoice_needs_review(extraction: InvoiceExtraction) -> bool:
    return (
        extraction.confidence < 0.65
        or not extraction.invoice_number
        or not extraction.total_amount
        or not extraction.date
    )


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,:;")
    return None


def _line_value(text: str, labels: list[str]) -> str | None:
    for label in labels:
        match = re.search(
            rf"^\s*{re.escape(label)}\s*[:#-]\s*(.+?)\s*$", text, flags=re.IGNORECASE | re.MULTILINE
        )
        if match:
            return match.group(1).strip(" .,:;")
    return None


def _date_from_label(text: str, labels: list[str]) -> date | None:
    for label in labels:
        value = _line_value(text, [label])
        if value:
            parsed = parse_spanish_date(value)
            if parsed:
                return parsed
    return first_date_in_text(text)


def _amount_from_label(text: str, labels: list[str]) -> tuple[float | None, str | None]:
    for label in labels:
        pattern = (
            rf"^\s*{re.escape(label)}(?:\s+\d{{1,2}}%)?\s*[:#-]\s*([0-9][0-9.,]*)\s*(€|eur|euros)?"
        )
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return _parse_amount(match.group(1)), _currency(match.group(2))
    return None, None


def _tax_id(text: str) -> str | None:
    return _first_match(
        text,
        [
            r"\b(?:nif|cif)\s*[:#-]?\s*([A-Z]\d{7,8}[A-Z0-9]?)",
            r"\b(?:nif|cif)\s*[:#-]?\s*(\d{8}[A-Z])",
        ],
    )


def _parse_date(value: str) -> date | None:
    """Backwards-compatible alias for :func:`parse_spanish_date`.

    Kept so existing callers and tests that imported ``_parse_date``
    from this module keep working. The real implementation now
    lives in :mod:`app.services.dates` and also accepts textual
    Spanish dates like ``"15 de junio de 2026"``.
    """
    return parse_spanish_date(value)


def _total_amount(text: str, qualifier: str) -> tuple[float | None, str | None]:
    patterns = [
        rf"\btotal\s+{re.escape(qualifier)}\s*[:#-]?\s*([0-9][0-9.,]*)\s*(€|eur|euros)?",
        r"\btotal\s*[:#-]?\s*([0-9][0-9.,]*)\s*(€|eur|euros)?",
    ]
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if matches:
            amount = _parse_amount(matches[-1].group(1))
            currency = _currency(matches[-1].group(2))
            return amount, currency
    return None, None


def _currency(raw: str | None) -> str | None:
    if not raw:
        return None
    normalized = raw.lower()
    if normalized in {"€", "eur", "euros"}:
        return "EUR"
    return raw.upper()


def _status(text: str) -> str | None:
    """Detect the budget status.

    Scoped to the area around a status label ("Estado:", "Situación:",
    "Status:") so stray text in the document body — clauses like
    "política de cancelación" or "pendiente de revisión" in a footer
    — does not flip the document status.

    Falls back to a whole-document scan only if no label is present,
    so documents that do not use a label still get a value.
    """
    label_match = re.search(
        r"^\s*(?:estado|situaci[oó]n|status)\s*[:#-]\s*(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if label_match:
        value = label_match.group(1).lower()
        return _classify_status_value(value)
    # Fallback: whole-document scan (preserves the old behaviour for
    # documents that do not carry a status label).
    return _classify_status_value(text.lower())


def _classify_status_value(value: str) -> str | None:
    if any(word in value for word in ["aceptado", "aprobado", "confirmado"]):
        return "aceptado"
    if "cancelado" in value or "anulado" in value or "rechazado" in value:
        return "cancelado"
    if "pendiente" in value:
        return "pendiente"
    return None


def _validate_extraction(
    extraction: BudgetExtraction | OrderExtraction | InvoiceExtraction,
) -> list[ValidationIssue]:
    """Cross-check the extracted values for internal coherence.

    Returns a list of :class:`ValidationIssue` objects describing the
    discrepancies found. An empty list means the document passed all
    available checks. The checks are deliberately tolerant: amounts
    are compared with a small relative tolerance because the OCR
    pipeline regularly rounds or drops cents. Hard mismatches still
    surface as a clear :class:`ValidationIssue`.
    """
    issues: list[ValidationIssue] = []

    def _approx_eq(a: float, b: float, *, abs_tol: float = 0.05, rel_tol: float = 0.02) -> bool:
        if a is None or b is None:
            return False
        return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))

    # 1) Per-line: quantity × unit_price ≈ total_price.
    lines = getattr(extraction, "lines", None) or []
    for idx, line in enumerate(lines, start=1):
        qty = line.quantity
        price = line.unit_price
        total = line.total_price
        if qty is not None and price is not None and total is not None:
            expected = round(qty * price, 2)
            if not _approx_eq(expected, total):
                issues.append(
                    ValidationIssue(
                        check="line_qty_price_total",
                        field=f"lines[{idx}].total_price",
                        expected=expected,
                        actual=total,
                        detail=f"line {idx}: {qty} × {price} = {expected} but total_price is {total}",
                    )
                )

    # 2) Subtotal: Σ(line.total_price) ≈ total_amount (or taxable_base
    #    for invoices, where total = base + VAT).
    line_sum = round(
        sum(ln.total_price for ln in lines if ln.total_price is not None),
        2,
    )
    total_amount = getattr(extraction, "total_amount", None)
    if (
        total_amount is not None
        and line_sum > 0
        and not _approx_eq(line_sum, total_amount, abs_tol=0.5, rel_tol=0.01)
    ):
        issues.append(
            ValidationIssue(
                check="subtotal_vs_total",
                field="total_amount",
                expected=line_sum,
                actual=total_amount,
                detail=f"sum(line.total_price)={line_sum} but total_amount={total_amount}",
            )
        )

    # 3) Invoice coherence: base + VAT ≈ total.
    if isinstance(extraction, InvoiceExtraction):
        base = extraction.taxable_base
        vat = extraction.vat_amount
        total = extraction.total_amount
        if base is not None and vat is not None and total is not None:
            expected = round(base + vat, 2)
            if not _approx_eq(expected, total, abs_tol=0.05):
                issues.append(
                    ValidationIssue(
                        check="base_vat_total",
                        field="total_amount",
                        expected=expected,
                        actual=total,
                        detail=f"base({base}) + vat({vat}) = {expected} but total_amount={total}",
                    )
                )
        elif base is not None and total is not None and vat is None:
            # VAT is missing but we have base and total — at least
            # warn that VAT could not be validated.
            issues.append(
                ValidationIssue(
                    check="missing_vat",
                    field="vat_amount",
                    expected=None,
                    actual=None,
                    detail="taxable_base and total_amount present but vat_amount missing",
                )
            )
    return issues


def _issues_to_reasons(issues: list[ValidationIssue]) -> list[str]:
    """Translate ValidationIssue objects into short, human-readable
    reasons. Used to populate ``PersistedBusinessExtraction.review_reasons``."""
    out: list[str] = []
    for issue in issues:
        if issue.check == "line_qty_price_total":
            out.append(f"coherencia_linea:{issue.detail}")
        elif issue.check == "subtotal_vs_total":
            out.append(f"coherencia_subtotal:esperado={issue.expected} real={issue.actual}")
        elif issue.check == "base_vat_total":
            out.append(f"coherencia_iva:base+vat={issue.expected} total={issue.actual}")
        elif issue.check == "missing_vat":
            out.append("falta_iva:base_y_total_presentes_sin_importe_iva")
        else:
            out.append(f"{issue.check}:{issue.detail or ''}")
    return out


def _has_table_blocks(pages: list[ExtractedPage] | None) -> bool:
    """Return True if any page contains a block with
    ``block_type == 'table'``.

    The vision-LLM fallback in :mod:`app.parsers.pdf` emits the
    transcribed table as a markdown ``ExtractedBlock`` with
    ``block_type='table'``; the layout-aware clustering in
    :mod:`app.services.extraction.table_extraction` works on raw
    OCR rows, not on these blocks. We use the table block as a
    pre-validated structured signal whenever it is present.
    """
    if not pages:
        return False
    for page in pages:
        for block in page.blocks:
            if block.block_type == "table" and block.text:
                return True
    return False


def _parse_markdown_table(markdown: str) -> list[ExtractedLine]:
    """Parse a markdown table into :class:`ExtractedLine` rows.

    The vision LLM emits tables as pipe-delimited markdown
    (``| REF | DESC | CANT | TOTAL |``) with a separator row of
    dashes. The parser is tolerant: missing columns become None,
    extra columns are folded into the description, and a header
    row is auto-detected by looking for a single token that does
    not parse as a number.

    Returns an empty list when ``markdown`` is not a recognisable
    table so the caller can fall back to the layout-aware /
    regex extractors.
    """
    if not markdown:
        return []
    rows_raw: list[list[str]] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        # Skip the separator row: "|---|---|" or "| --- |"
        if re.fullmatch(r"\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", line):
            continue
        # Split on '|', drop the leading and trailing empty cells
        # produced by the leading and trailing pipes.
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not any(cells):
            continue
        rows_raw.append(cells)
    if len(rows_raw) < 2:
        return []
    # Detect header: first row is treated as the header if at least
    # half of its cells are non-numeric.
    header = rows_raw[0]
    numeric_cells = sum(1 for c in header if _looks_numeric(c))
    header_is_label = numeric_cells < max(1, len(header) // 2)
    body = rows_raw[1:] if header_is_label else rows_raw
    if not header_is_label:
        # Synthesise a 4-column default: ref, desc, qty, total.
        header = ["col0", "descripcion", "col2", "total"]
    lines: list[ExtractedLine] = []
    for row in body:
        mapped = _map_row_to_line(row, header)
        if mapped is not None:
            lines.append(mapped)
    return lines


def _looks_numeric(value: str) -> bool:
    """Heuristic: does ``value`` look like a number or currency?"""
    if not value:
        return False
    cleaned = re.sub(r"[€$£\s]", "", value)
    return bool(re.fullmatch(r"-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?", cleaned))


def _map_row_to_line(row: list[str], header: list[str]) -> ExtractedLine | None:
    """Map one body row to an :class:`ExtractedLine` using the
    header column labels. Recognised labels (case-insensitive
    whole-word): ``ref``/``referencia`` → reference, ``desc``/
    ``descripcion``/``concepto`` → description, ``cant``/``qty``/
    ``unidades`` → quantity, ``precio``/``p.unit``/``unit`` →
    unit_price, ``total``/``importe`` → total_price.

    Unrecognised columns are appended to the description. Rows
    that contain no usable signal are dropped.
    """
    if not row:
        return None
    values: dict[str, object] = {
        "reference": None,
        "description": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "total_price": None,
    }
    for idx, cell in enumerate(row):
        if idx >= len(header):
            break
        label = header[idx].strip().lower()
        cell_str = cell.strip()
        if not cell_str:
            continue
        if re.search(r"\b(ref|referencia|c[oó]digo|art)\b", label):
            values["reference"] = cell_str
        elif re.search(r"\b(desc|descripci[oó]n|concepto|detalle)\b", label):
            values["description"] = (
                f"{values['description']} {cell_str}".strip() if values["description"] else cell_str
            )
        elif re.search(r"\b(cant|cantidad|qty|unidades)\b", label):
            values["quantity"] = _parse_amount(cell_str)
        elif re.search(r"\b(precio|p\.?\s*unit|unit|tarifa)\b", label):
            values["unit_price"] = _parse_amount(cell_str)
        elif re.search(r"\b(total|importe|subtotal)\b", label):
            values["total_price"] = _parse_amount(cell_str)
        else:
            # Unrecognised column — fold it into the description so
            # the LLM still sees the text.
            values["description"] = (
                f"{values['description']} {cell_str}".strip() if values["description"] else cell_str
            )
    if not any(values.values()):
        return None
    return ExtractedLine(
        reference=values["reference"]
        if isinstance(values["reference"], (str, type(None)))
        else None,
        description=values["description"]
        if isinstance(values["description"], (str, type(None)))
        else None,
        quantity=values["quantity"]
        if isinstance(values["quantity"], (int, float, type(None)))
        else None,
        unit=values["unit"] if isinstance(values["unit"], (str, type(None))) else None,
        unit_price=values["unit_price"]
        if isinstance(values["unit_price"], (int, float, type(None)))
        else None,
        total_price=values["total_price"]
        if isinstance(values["total_price"], (int, float, type(None)))
        else None,
        confidence=0.90,  # structured table → higher than the regex fallback
    )


def _extract_lines_for_document(
    text: str,
    pages: list[ExtractedPage] | None = None,
) -> list[ExtractedLine]:
    """Pick the best line-extraction strategy for the document.

    Strategy order:

    1. **Structured table block.** If any :class:`ExtractedPage`
       carries an ``ExtractedBlock`` with ``block_type='table'``,
       parse the markdown table embedded in the block. The vision
       LLM emits this shape for hard-to-OCR pages; bypassing the
       regex means we keep the row alignment the vision model
       produced.
    2. **Layout-aware clustering.** When the pages carry bounding
       boxes (from PaddleOCR or the digital-text path), use
       :mod:`app.services.extraction.table_extraction` to cluster
       rows and columns.
    3. **Legacy regex.** The original single-line pattern, kept
       as a safety net for the paths where neither structured
       data nor bounding boxes are available.
    """
    if _has_table_blocks(pages):
        # ``_has_table_blocks`` guarantees ``pages`` is a non-empty
        # sequence; assert is dead code and would be stripped by
        # ``python -O`` so we no-op it here.
        table_lines: list[ExtractedLine] = []
        for page in pages:
            for block in page.blocks:
                if block.block_type == "table" and block.text:
                    table_lines.extend(_parse_markdown_table(block.text))
        if table_lines:
            return table_lines
        logger.debug(
            "Found table blocks but parsing produced no lines; falling back to layout-aware path."
        )
    if pages:
        try:
            from app.services.extraction import extract_lines_from_pages

            lines = extract_lines_from_pages(pages)
            if lines:
                return lines
            logger.debug("Layout-aware extraction returned no lines; falling back to regex.")
        except Exception as exc:
            logger.warning(
                "Layout-aware line extraction failed (%s); falling back to regex.",
                exc,
            )
    return _extract_lines(text)


def _extract_lines(text: str) -> list[ExtractedLine]:
    """Legacy single-line regex extractor. Kept for backward compatibility
    and as a fallback when layout-aware extraction finds no table."""
    lines: list[ExtractedLine] = []
    pattern = re.compile(
        r"^\s*(?P<reference>[A-Z0-9][A-Z0-9_./-]{2,})\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<quantity>\d+(?:[,.]\d+)?)\s+"
        r"(?P<unit>[A-Za-zñÑ²2]+)\s+"
        r"(?P<unit_price>\d[\d.,]*)\s+"
        r"(?P<total_price>\d[\d.,]*)\s*$",
        flags=re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        match = pattern.match(raw_line)
        if not match:
            continue
        lines.append(
            ExtractedLine(
                reference=match.group("reference").strip(),
                description=match.group("description").strip(),
                quantity=_parse_amount(match.group("quantity")),
                unit=match.group("unit").strip(),
                unit_price=_parse_amount(match.group("unit_price")),
                total_price=_parse_amount(match.group("total_price")),
                # Layout-aware path (see
                # ``app.services.extraction.table_extraction``)
                # computes a per-line confidence from the OCR
                # confidence of the source blocks. This regex
                # fallback runs only when no bounding boxes are
                # available, so we have no OCR signal to lean on;
                # the value below is therefore a conservative
                # "we matched the pattern, no idea on OCR quality"
                # placeholder. Calibrate against a labelled sample
                # before changing it.
                confidence=0.82,
            )
        )
    return lines


def _parse_amount(value: str | None, locale: str = "es-ES") -> float | None:
    """Parse a numeric string into a float.

    The default ``es-ES`` locale treats ``.`` as the thousands separator
    and ``,`` as the decimal separator. This matches the dominant
    convention for Spanish quotes/orders/invoices. Ambiguous strings
    like ``"1.234"`` (no comma) are resolved as es-ES thousands, i.e.
    ``1234.0``; this is the safe choice for the project's target
    suppliers and matches the explicit tests in
    :mod:`tests.test_business_extraction`.

    For non-es-ES suppliers, pass ``locale="en-US"`` (``.`` is decimal,
    ``,`` is thousands) or ``locale="it-IT"`` (same as es-ES).
    """
    if not value:
        return None
    clean = value.strip().replace(" ", "").replace("\u00a0", "")
    if not clean:
        return None
    locale = (locale or "es-ES").lower()
    if locale in {"es-es", "es", "it-it", "it", "de-de", "de", "fr-fr", "fr"}:
        # ``.`` is thousands, ``,`` is decimal.
        if "," in clean and "." in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean:
            # Could be decimal ("12,5") or thousands ("1,234").
            # es-ES default: treat as decimal when there's at most one
            # comma and the part after it has 1-2 digits. Otherwise
            # treat as thousands (rare in invoices but possible).
            parts = clean.split(",")
            if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")
        elif "." in clean:
            # Only dots → es-ES thousands. "1.234" → "1234".
            # If the part after the last dot is 3 digits, treat as
            # thousands. Otherwise (e.g. "1.23"), it's a malformed
            # decimal — best effort: strip the dots and parse.
            parts = clean.split(".")
            if all(p.isdigit() and 1 <= len(p) <= 3 for p in parts):
                clean = clean.replace(".", "")
            # else: fall through with dots preserved (will parse as
            # the float "1.23" → 1.23). This is the legacy behaviour
            # and is rare in practice.
    elif locale in {"en-us", "en", "en-gb"}:
        if "," in clean and "." in clean:
            # If the dot comes after the last comma, comma is thousands.
            last_dot = clean.rfind(".")
            last_comma = clean.rfind(",")
            if last_dot > last_comma:
                clean = clean.replace(",", "")
            else:
                clean = clean.replace(",", "").replace(".", "")
        elif "," in clean:
            # Only commas → en-US thousands. "1,234" → "1234".
            clean = clean.replace(",", "")
        # else: only dots → en-US decimal. "1.234" → "1.234".
    else:
        # Unknown locale: fall back to the legacy symbol-presence rule.
        if "," in clean and "." in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean:
            clean = clean.replace(",", ".")
    try:
        return round(float(clean), 2)
    except ValueError:
        return None


def _confidence(document_confidence: float | None, fields: list[object], has_lines: bool) -> float:
    present = sum(1 for field in fields if field not in (None, ""))
    base = 0.35 + present * 0.11 + (0.10 if has_lines else 0)
    if document_confidence is not None:
        base = (base + document_confidence) / 2
    return round(min(0.98, max(0.35, base)), 2)


def _amount_text(value: float | None) -> str | None:
    return f"{value:.2f}" if value is not None else None
