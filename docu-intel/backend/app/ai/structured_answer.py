"""Fast, cited answers for trusted structured facts."""
from __future__ import annotations

import json
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
    # Dossier items (no document_id) are handled first so the
    # catalogue / aggregation answers win over the per-document checks.
    # Trap-word guard: if the question mentions a concept the docs do
    # not contain (e.g. "piscina", "IRPF", "director general", "margen
    # de beneficio"), the structured_answer renderer should NOT use a
    # coincidental keyword match (e.g. "proveedor" inside the question)
    # to surface an unrelated field from a real document. The renderer
    # only blocks the per-field matchers (supplier/client/etc); the
    # dossier renderer above is left untouched because dossier
    # answers come from the catalogue, not from inferred fields.
    trap_words = (
        "piscina", "irpf", "margen", "director general", "director",
        "beneficio", "roi", "impuesto", "tax", "pérdida", "ganancia",
    )
    question_low = (question or "").lower()
    has_trap = any(w in question_low for w in trap_words)

    for item in context_items:
        if item.document_id is not None:
            continue
        title = item.title or ""
        title = item.title or ""
        # 1) list_distinct_budget_codes
        if title == "[Dossier] presupuestos distintos":
            codes = item.summary.split(",") if item.summary else []
            if not codes or codes == [""]:
                return _decision(
                    item, "No se encontraron presupuestos registrados en el sistema."
                )
            n = len(codes)
            list_text = ", ".join(codes[:20]) + ("..." if n > 20 else "")
            return _decision(
                item, f"He encontrado {n} presupuestos distintos: {list_text}."
            )
        # 2) list_documents_by_budget_code
        if title.startswith("[Dossier] ") and " del presupuesto " in title:
            try:
                docs = json.loads(item.excerpt or "[]")
            except (ValueError, TypeError):
                docs = []
            if not docs:
                return _decision(
                    item, f"{item.title.split(' del presupuesto ')[0].replace('[Dossier] ', '')} no encontrados para el presupuesto {title.split(' del presupuesto ')[-1]} con esos filtros."
                )
            quality_badges = {
                "needs_human_review": " (revision)",
                "usable_with_warnings": " (con advertencias)",
                "duplicate": " (duplicado)",
                "pending": " (pendiente)",
            }
            lines = [f"He encontrado {len(docs)} documentos:"]
            for d in docs[:20]:
                badge = quality_badges.get(d.get("quality_status", ""), "")
                fname = (d.get("filename") or "?")[:60]
                lines.append(
                    f"- id={d.get('id')} {fname}{badge} [{d.get('document_type', '?')}]"
                )
            if len(docs) > 20:
                lines.append(f"... y {len(docs) - 20} mas.")
            first_id = docs[0].get("id")
            return _decision(
                item, "\n".join(lines),
                document_id=first_id, filename=docs[0].get("filename"),
            )
        # 3) get_budget_summary
        if title.startswith("[Dossier] resumen ejecutivo "):
            try:
                summary = json.loads(item.excerpt or "{}")
            except (ValueError, TypeError):
                summary = {}
            if not summary.get("found"):
                return _decision(
                    item, f"No se encontro el presupuesto {summary.get('budget_code', 'indicado')}."
                )
            by_type = summary.get("by_type", {})
            by_quality = summary.get("by_quality", {})
            top_types = sorted(by_type.items(), key=lambda x: -x[1])[:5]
            top_q = sorted(by_quality.items(), key=lambda x: -x[1])[:5]
            lines = [
                f"Presupuesto {summary['budget_code']}: {summary['document_count']} documentos.",
                "Por tipo: " + ", ".join(f"{k}={v}" for k, v in top_types),
                "Por calidad: " + ", ".join(f"{k}={v}" for k, v in top_q),
            ]
            return _decision(item, "\n".join(lines))
        # 4) find_nearest_budget
        if title.startswith("[Dossier] nearest_budget "):
            try:
                near = json.loads(item.summary or "{}")
            except (ValueError, TypeError):
                near = {}
            if not near:
                return _decision(
                    item, "No hay presupuestos en el sistema para comparar."
                )
            if "exact" in near:
                return _decision(
                    item, f"Si, el presupuesto {near['exact']} existe."
                )
            parts = []
            if "above" in near:
                parts.append(f"el siguiente existente es {near['above']}")
            if "below" in near:
                parts.append(f"el anterior existente es {near['below']}")
            target = title.split("nearest_budget ")[-1]
            return _decision(
                item,
                f"El presupuesto {target} no existe. " + "; ".join(parts) +
                f". El mas cercano es {near.get('closest')}.",
            )
        # 5) find_documents_by_reference
        if title.startswith("[Dossier] reference_search "):
            try:
                refs = json.loads(item.excerpt or "[]")
            except (ValueError, TypeError):
                refs = []
            if not refs:
                return _decision(
                    item, "No se encontraron documentos con esa referencia."
                )
            lines = [f"He encontrado {len(refs)} documentos:"]
            for d in refs[:10]:
                dup = ""
                if d.get("quality_status") == "duplicate" and d.get("duplicate_of_document_id"):
                    dup = f" (duplicado de id={d['duplicate_of_document_id']})"
                lines.append(
                    f"- id={d.get('id')} {d.get('filename', '?')[:50]} "
                    f"[{d.get('document_type', '?')}, {d.get('quality_status', '?')}]{dup}"
                )
            if len(refs) > 10:
                lines.append(f"... y {len(refs) - 10} mas.")
            return _decision(
                item, "\n".join(lines),
                document_id=refs[0].get("id"),
                filename=refs[0].get("filename"),
            )

    for item in context_items:
        if item.document_id is None or (
            item.confidence is not None and item.confidence < 0.7
        ):
            continue
        summary = item.summary or ""
        evidence = "\n".join(part for part in (summary, item.excerpt) if part)
        if _AMOUNT_QUESTION.search(question) and can_view_prices and not has_trap:
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
        if _SUPPLIER_QUESTION.search(question) and not has_trap:
            match = _SUPPLIER_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"El proveedor es {match.group(1).strip()}")
        if _CLIENT_QUESTION.search(question) and not has_trap:
            match = _CLIENT_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"El cliente es {match.group(1).strip()}")
        if _STATUS_QUESTION.search(question) and not has_trap:
            match = _STATUS_IN_SUMMARY.search(summary)
            if match and match.group(1).strip() != "-":
                return _decision(item, f"El estado es {match.group(1).strip()}")
        if _DATE_QUESTION.search(question) and not has_trap:
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


def _decision(
    item: ContextItem,
    statement: str,
    *,
    document_id: int | None = None,
    filename: str | None = None,
) -> StructuredAnswerDecision:
    """Create a source-carrying decision after a field has passed validation.

    The optional ``document_id`` and ``filename`` overrides let dossier
    renderers attach the first matching document as the citation anchor
    (so the UI can render a clickable "view in document" link).
    """
    label = item.document_filename or item.title.replace("[Estructurado] ", "")
    # Dossier items intentionally do not embed "segun X" because the
    # list itself is the answer; only attach the citation anchor when
    # a specific document was returned.
    if document_id is None and filename is None:
        return StructuredAnswerDecision(
            answer=statement,
            document_id=item.document_id or 0,
            filename=item.document_filename,
            page_number=item.page_number,
        )
    return StructuredAnswerDecision(
        answer=statement,
        document_id=document_id or 0,
        filename=filename or label,
        page_number=item.page_number,
    )
