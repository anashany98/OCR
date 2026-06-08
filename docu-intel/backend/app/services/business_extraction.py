from __future__ import annotations

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
class PersistedBusinessExtraction:
    budget: Budget | None = None
    order: Order | None = None
    invoice: Invoice | None = None
    needs_review: bool = False


def extract_budget(document_id: int, text: str, document_confidence: float | None) -> BudgetExtraction | None:
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
    lines = _extract_lines(text)

    score = _confidence(document_confidence, [budget_number, client_name, parsed_date, total_amount], bool(lines))
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


def extract_order(document_id: int, text: str, document_confidence: float | None) -> OrderExtraction | None:
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
    related_budget_number = _line_value(text, ["presupuesto relacionado", "presupuesto ref", "presupuesto"])
    if related_budget_number:
        related_budget_number = related_budget_number.split()[0].strip(" .,:;")
    lines = _extract_lines(text)

    score = _confidence(document_confidence, [order_number, supplier_name, parsed_date, total_amount], bool(lines))
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


def extract_invoice(document_id: int, text: str, document_confidence: float | None) -> InvoiceExtraction | None:
    if not text.strip():
        return None

    invoice_number = _first_match(
        text,
        [
            r"\bfactura\s*(?:n[ºo]\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./-]{1,})",
            r"\bn[ºo]\s*factura\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{1,})",
        ],
    )
    supplier_name = _line_value(text, ["proveedor", "emisor", "empresa", "razon social", "razón social"])
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
        [invoice_number, supplier_name, supplier_tax_id, parsed_date, taxable_base, vat_amount, total_amount],
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


def persist_business_extraction(db: Session, document: Document, text: str) -> PersistedBusinessExtraction:
    _delete_existing_business_data(db, document.id)

    if document.document_type == "presupuesto":
        extraction = extract_budget(document.id, text, document.confidence)
        if not extraction:
            return PersistedBusinessExtraction(needs_review=True)
        budget = Budget(
            document_id=document.id,
            budget_number=extraction.budget_number,
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
        return PersistedBusinessExtraction(budget=budget, needs_review=_budget_needs_review(extraction))

    if document.document_type == "pedido":
        extraction = extract_order(document.id, text, document.confidence)
        if not extraction:
            return PersistedBusinessExtraction(needs_review=True)
        if extraction.date is None:
            _add_entities_for_order(db, document.id, extraction)
            return PersistedBusinessExtraction(needs_review=True)
        related_budget_id = _find_related_budget_id(db, extraction)
        order = Order(
            document_id=document.id,
            order_number=extraction.order_number,
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
        return PersistedBusinessExtraction(order=order, needs_review=_order_needs_review(extraction, related_budget_id))

    if document.document_type == "factura":
        extraction = extract_invoice(document.id, text, document.confidence)
        if not extraction:
            return PersistedBusinessExtraction(needs_review=True)
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
        return PersistedBusinessExtraction(invoice=invoice, needs_review=_invoice_needs_review(extraction))

    return PersistedBusinessExtraction()


def _delete_existing_business_data(db: Session, document_id: int) -> None:
    budget_ids = list(db.scalars(select(Budget.id).where(Budget.document_id == document_id)).all())
    order_ids = list(db.scalars(select(Order.id).where(Order.document_id == document_id)).all())
    invoice_ids = list(db.scalars(select(Invoice.id).where(Invoice.document_id == document_id)).all())
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
    _entity(db, document_id, "total_amount", _amount_text(extraction.total_amount), extraction.confidence)
    for line in extraction.lines:
        _entity(db, document_id, "reference", line.reference, line.confidence)


def _add_entities_for_order(db: Session, document_id: int, extraction: OrderExtraction) -> None:
    _entity(db, document_id, "order_number", extraction.order_number, extraction.confidence)
    _entity(db, document_id, "supplier_name", extraction.supplier_name, extraction.confidence)
    _entity(db, document_id, "client_name", extraction.client_name, extraction.confidence)
    _entity(db, document_id, "related_budget_number", extraction.related_budget_number, extraction.confidence)
    _entity(db, document_id, "total_amount", _amount_text(extraction.total_amount), extraction.confidence)
    for line in extraction.lines:
        _entity(db, document_id, "reference", line.reference, line.confidence)


def _add_entities_for_invoice(db: Session, document_id: int, extraction: InvoiceExtraction) -> None:
    _entity(db, document_id, "invoice_number", extraction.invoice_number, extraction.confidence)
    _entity(db, document_id, "supplier_name", extraction.supplier_name, extraction.confidence)
    _entity(db, document_id, "supplier_tax_id", extraction.supplier_tax_id, extraction.confidence)
    _entity(db, document_id, "client_name", extraction.client_name, extraction.confidence)
    _entity(db, document_id, "invoice_date", extraction.date.isoformat() if extraction.date else None, extraction.confidence)
    _entity(db, document_id, "taxable_base", _amount_text(extraction.taxable_base), extraction.confidence)
    _entity(db, document_id, "vat_amount", _amount_text(extraction.vat_amount), extraction.confidence)
    _entity(db, document_id, "total_amount", _amount_text(extraction.total_amount), extraction.confidence)
    _entity(db, document_id, "related_order_number", extraction.related_order_number, extraction.confidence)


def _entity(db: Session, document_id: int, entity_type: str, value: str | None, confidence: float) -> None:
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


def _find_related_budget_id(db: Session, extraction: OrderExtraction) -> int | None:
    if extraction.related_budget_number:
        budget = db.scalar(select(Budget).where(Budget.budget_number == extraction.related_budget_number).limit(1))
        if budget:
            return budget.id
    return None


def _find_related_order_id(db: Session, extraction: InvoiceExtraction) -> int | None:
    if extraction.related_order_number:
        order = db.scalar(select(Order).where(Order.order_number == extraction.related_order_number).limit(1))
        if order:
            return order.id
    return None


def _budget_needs_review(extraction: BudgetExtraction) -> bool:
    return extraction.confidence < 0.65 or not extraction.budget_number or not extraction.total_amount


def _order_needs_review(extraction: OrderExtraction, related_budget_id: int | None) -> bool:
    relation_was_expected = bool(extraction.related_budget_number)
    return extraction.confidence < 0.65 or not extraction.order_number or not extraction.total_amount or (
        relation_was_expected and related_budget_id is None
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
        match = re.search(rf"^\s*{re.escape(label)}\s*[:#-]\s*(.+?)\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip(" .,:;")
    return None


def _date_from_label(text: str, labels: list[str]) -> date | None:
    for label in labels:
        value = _line_value(text, [label])
        if value:
            parsed = _parse_date(value)
            if parsed:
                return parsed
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text)
    return _parse_date(match.group(1)) if match else None


def _amount_from_label(text: str, labels: list[str]) -> tuple[float | None, str | None]:
    for label in labels:
        pattern = rf"^\s*{re.escape(label)}(?:\s+\d{{1,2}}%)?\s*[:#-]\s*([0-9][0-9.,]*)\s*(€|eur|euros)?"
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
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", value)
    if not match:
        return None
    day, month, year = [int(part) for part in match.groups()]
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


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
    normalized = text.lower()
    if any(word in normalized for word in ["aceptado", "aprobado", "confirmado"]):
        return "aceptado"
    if "cancelado" in normalized:
        return "cancelado"
    if "pendiente" in normalized:
        return "pendiente"
    return None


def _extract_lines(text: str) -> list[ExtractedLine]:
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
                confidence=0.82,
            )
        )
    return lines


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    clean = value.strip().replace(" ", "")
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

