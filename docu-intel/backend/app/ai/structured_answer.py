"""Fast, cited answers for trusted structured facts."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.context import ContextItem


@dataclass(frozen=True)
class StructuredAnswerDecision:
    answer: str
    document_id: int
    filename: str | None
    page_number: int | None


_AMOUNT_QUESTION = re.compile(
    r"\b(importe|total|cuanto|precio|coste|costo)\b", re.IGNORECASE
)
_DOCUMENT_REFERENCE_QUESTION = re.compile(
    r"\b(?:documento|archivo)\b", re.IGNORECASE
)
_AMOUNT_IN_SUMMARY = re.compile(r"-\s*([0-9][0-9.,]*\s+[A-Z]{3})\s*-")
_DELIVERY_NOTE_QUESTION = re.compile(r"\balbar[aá]n(?:es)?\b", re.IGNORECASE)
_DELIVERY_NOTE_ENTRY = re.compile(
    r"Albar[aá]n:\s*([0-9]{4,})[\s\S]{0,500}?CONCEPTO:\s*"
    r"(Entrega|Recogida)\b",
    re.IGNORECASE,
)
_SUPPLIER_QUESTION = re.compile(r"\b(proveedor|suministrador)\b", re.IGNORECASE)
_CLIENT_QUESTION = re.compile(r"\b(cliente)\b", re.IGNORECASE)
_STATUS_QUESTION = re.compile(r"\b(estado|situacion)\b", re.IGNORECASE)
_DATE_QUESTION = re.compile(r"\b(fecha|cuando)\b", re.IGNORECASE)
_SUPPLIER_IN_SUMMARY = re.compile(r"Proveedor\s+(.+?)(?:\s+-|$)", re.IGNORECASE)
_CLIENT_IN_SUMMARY = re.compile(r"Cliente\s+(.+?)(?:\s+-|$)", re.IGNORECASE)
_STATUS_IN_SUMMARY = re.compile(r"Estado\s+([^\n-]+)", re.IGNORECASE)
_DATE_IN_SUMMARY = re.compile(r"Fecha:\s*([^\n]+)", re.IGNORECASE)


def decide_structured_answer(
    question: str,
    context_items: list[ContextItem],
    *,
    can_view_prices: bool,
) -> StructuredAnswerDecision | None:
    """Return a deterministic answer only when its source is explicit.

    This intentionally handles a narrow, high-confidence subset. Missing
    values, missing document ids, and low-confidence evidence stay on the
    grounded/LLM path.
    """
    for item in context_items:
        if item.document_id is None or (
            item.confidence is not None and item.confidence < 0.7
        ):
            continue
        summary = item.summary or ""
        evidence = "\n".join(part for part in (summary, item.excerpt) if part)
        if _AMOUNT_QUESTION.search(question) and can_view_prices:
            match = _AMOUNT_IN_SUMMARY.search(evidence)
            if match:
                return _decision(item, f"El importe total es {match.group(1)}")
        if _DELIVERY_NOTE_QUESTION.search(question):
            delivery_notes = _delivery_notes(evidence)
            if delivery_notes:
                if _AMOUNT_QUESTION.search(question) and can_view_prices:
                    return _decision(
                        item,
                        "No puedo confirmar el importe porque el albaran disponible no contiene un total legible",
                    )
                rendered = " y ".join(
                    f"{number} ({kind.lower()})" for number, kind in delivery_notes
                )
                return _decision(item, f"Los albaranes son {rendered}")
        if _SUPPLIER_QUESTION.search(question):
            match = _SUPPLIER_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"El proveedor es {match.group(1).strip()}")
        if _CLIENT_QUESTION.search(question):
            match = _CLIENT_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"El cliente es {match.group(1).strip()}")
        if _STATUS_QUESTION.search(question):
            match = _STATUS_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"El estado es {match.group(1).strip()}")
        if _DATE_QUESTION.search(question):
            match = _DATE_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"La fecha es {match.group(1).strip()}")

    # An exact document lookup can be useful even if the amount was not
    # extracted. State the evidence limitation instead of letting a model
    # infer or fabricate an amount from unrelated context.
    if (
        _AMOUNT_QUESTION.search(question)
        and can_view_prices
        and _DOCUMENT_REFERENCE_QUESTION.search(question)
    ):
        for item in context_items:
            if item.document_id is None:
                continue
            evidence = "\n".join(part for part in (item.summary, item.excerpt) if part)
            if not _AMOUNT_IN_SUMMARY.search(evidence):
                return _decision(
                    item,
                    "No puedo confirmar el importe total con el texto extraido disponible",
                )

    return None


def _delivery_notes(evidence: str) -> list[tuple[str, str]]:
    """Return unique delivery-note number/type pairs in their source order."""
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for number, kind in _DELIVERY_NOTE_ENTRY.findall(evidence):
        entry = (number, kind)
        if entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def _decision(item: ContextItem, statement: str) -> StructuredAnswerDecision:
    """Create a source-carrying decision after a field has passed validation."""
    label = item.document_filename or item.title.replace("[Estructurado] ", "")
    return StructuredAnswerDecision(
        answer=f"{statement} segun {label}.",
        document_id=item.document_id,
        filename=item.document_filename,
        page_number=item.page_number,
    )
