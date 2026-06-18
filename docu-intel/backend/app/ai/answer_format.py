"""CTX-9 — Standard grounded answer format.

The user-facing response has five sections, in this order:

1. **Respuesta directa** — the one-line answer the user came for.
2. **Evidencia** — the structured numbers / entities we found.
3. **Documentos usados** — the source documents the answer cites.
4. **Advertencias de confianza** — OCR low, duplicate, unknown type, …
5. **Que falta** — what the assistant could not find.

The :func:`format_grounded_answer` helper renders this layout for the
backend's grounded fallback. The LLM path is told (via the system
prompt) to follow the same layout when it cannot produce natural
prose — typically when the gate warnings force it to be honest.

The function is pure (no I/O). It accepts the same arguments the
existing :func:`app.ai.context.build_grounded_response` accepts plus
a small ``direct`` field for the one-line answer (or ``None`` when
the assistant is just citing a quote). When ``direct`` is ``None``
the function falls back to the existing quote-style lead text so
the legacy behaviour is preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .active_context import ActiveContext
from .context import ContextItem, _format_source


# ---------------------------------------------------------------------------
# Section dataclass
# ---------------------------------------------------------------------------


@dataclass
class GroundedAnswerSections:
    direct: str | None
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_paragraphs(self) -> list[str]:
        paragraphs: list[str] = []
        if self.direct:
            paragraphs.append(self.direct)
        if self.evidence:
            paragraphs.append(
                "**Evidencia:**\n" + "\n".join(f"- {line}" for line in self.evidence)
            )
        if self.sources:
            paragraphs.append(
                "**Documentos usados:**\n"
                + "\n".join(f"- {line}" for line in self.sources)
            )
        if self.warnings:
            paragraphs.append(
                "**Advertencias:**\n"
                + "\n".join(f"- {line}" for line in self.warnings)
            )
        if self.missing:
            paragraphs.append(
                "**Que falta:**\n"
                + "\n".join(f"- {line}" for line in self.missing)
            )
        return paragraphs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_sections(
    *,
    context_items: list[ContextItem],
    warnings: Iterable[str],
    direct: str | None = None,
    missing: Iterable[str] | None = None,
    active_context: ActiveContext | None = None,
) -> GroundedAnswerSections:
    """Compose the five sections from the context + warnings.

    ``direct`` is the one-line answer. ``missing`` is the list of
    things the user might have asked about that the assistant could
    not find (e.g. "no he encontrado un albaran de entrega dentro del
    presupuesto activo"). ``active_context`` is used to mention the
    active budget in the ``missing`` section so the user knows the
    scope was respected.
    """
    sections = GroundedAnswerSections(direct=direct)
    seen_warnings: set[str] = set()
    for warning in warnings or []:
        if not warning or warning in seen_warnings:
            continue
        seen_warnings.add(warning)
        sections.warnings.append(warning)

    seen_sources: set[str] = set()
    seen_evidence: set[str] = set()
    for item in context_items:
        # Sources
        if item.document_id is not None:
            source = _format_source(item)
            if source not in seen_sources:
                seen_sources.add(source)
                sections.sources.append(source)
        # Evidence: every structured-tool payload is rendered as a
        # one-line fact, and every other context item contributes the
        # first sentence of its excerpt.
        if item.title.startswith("[Estructurado]"):
            fact = _one_line_evidence_from_structured(item)
            if fact and fact not in seen_evidence:
                seen_evidence.add(fact)
                sections.evidence.append(fact)
        else:
            fact = _one_line_evidence_from_text(item)
            if fact and fact not in seen_evidence:
                seen_evidence.add(fact)
                sections.evidence.append(fact)

    for miss in missing or []:
        sections.missing.append(miss)
    if active_context is not None and active_context.has_budget_scope and not context_items:
        sections.missing.append(
            f"No he encontrado resultados dentro del presupuesto "
            f"{active_context.current_budget_number}. Si quieres buscar en "
            f"todos los documentos, dilo explicitamente."
        )

    return sections


def format_grounded_answer(
    *,
    context_items: list[ContextItem],
    warnings: Iterable[str],
    direct: str | None = None,
    missing: Iterable[str] | None = None,
    active_context: ActiveContext | None = None,
) -> str:
    """Return the full text of the grounded answer."""
    sections = build_sections(
        context_items=context_items,
        warnings=warnings,
        direct=direct,
        missing=missing,
        active_context=active_context,
    )
    return "\n\n".join(sections.to_paragraphs())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _one_line_evidence_from_structured(item: ContextItem) -> str | None:
    """Render a structured-tool ``ContextItem`` as a one-line fact.

    Parses the JSON payload carried in ``excerpt``/``summary`` and
    picks the field that is most useful as a fact. For
    ``get_budget_total`` the fact is the total amount; for
    ``get_invoiced_amount_for_budget`` the fact is the invoiced
    amount; etc.
    """
    import json

    payload_raw = item.excerpt or item.summary or ""
    if not payload_raw:
        return None
    try:
        payload = json.loads(payload_raw)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    label = item.title.replace("[Estructurado] ", "")

    # get_budget_total
    if "total_amount" in payload and "budget_number" in payload:
        if not payload.get("found"):
            return f"{label}: no encontrado en la base estructurada."
        amount = payload.get("total_amount")
        currency = payload.get("currency") or ""
        if amount is None:
            return f"{label}: no se ha detectado un importe total."
        return (
            f"{label}: {amount:.2f} {currency}".strip()
            + (
                f" — {int(round(float(payload.get('confidence') or 0) * 100))}% confianza"
                if payload.get("confidence")
                else ""
            )
        )

    # get_invoiced_amount_for_budget
    if "invoiced" in payload and "budget_number" in payload:
        if not payload.get("found"):
            return f"{label}: no encontrado en la base estructurada."
        inv = float(payload.get("invoiced") or 0.0)
        return (
            f"{label}: facturado {inv:.2f} EUR en "
            f"{int(payload.get('invoice_count') or 0)} factura(s)."
        )

    # list_recent_accepted_budgets
    if "budgets" in payload:
        items = payload.get("budgets") or []
        if not items:
            return f"{label}: sin resultados."
        sample = ", ".join(
            f"{b.get('budget_number')} ({b.get('client_name') or 'cliente ?'})"
            for b in items[:3]
        )
        return f"{label}: {len(items)} resultado(s). Ejemplo: {sample}."

    # find_delivery_note_in_scope
    if "matches" in payload:
        matches = payload.get("matches") or []
        if not matches:
            return f"{label}: sin coincidencias en el ambito activo."
        sample = ", ".join(m.get("filename") or "?" for m in matches[:3])
        return f"{label}: {len(matches)} candidato(s) — {sample}."

    # find_shipping_cost_in_scope
    if "candidates" in payload:
        candidates = payload.get("candidates") or []
        if not candidates:
            return f"{label}: sin coincidencias en el ambito activo."
        sample = ", ".join(
            (c.get("excerpt") or "")[:80] for c in candidates[:2]
        )
        return f"{label}: {len(candidates)} candidato(s) con palabras clave de envio."

    # get_invoice_origin_order
    if "order" in payload and "invoice_number" in payload:
        if not payload.get("found"):
            return f"{label}: factura no encontrada."
        order = payload.get("order") or {}
        if not order:
            return f"{label}: la factura no esta vinculada a ningun pedido."
        return (
            f"{label}: pedido {order.get('order_number') or '?'} "
            f"({order.get('supplier_name') or 'proveedor ?'})"
        )

    # get_budget_lines
    if "lines" in payload:
        lines = payload.get("lines") or []
        if not lines:
            return f"{label}: sin lineas extraidas."
        sample = "; ".join(
            (ln.get("description") or ln.get("reference") or "?")[:60]
            for ln in lines[:3]
        )
        return f"{label}: {len(lines)} linea(s) — {sample}."

    return f"{label}: datos estructurados disponibles."


def _one_line_evidence_from_text(item: ContextItem) -> str | None:
    text = (item.excerpt or item.summary or "").strip()
    if not text:
        return None
    first = text.split("\n", 1)[0].strip()
    if not first:
        return None
    label = item.document_filename or item.title or "documento"
    if len(first) > 160:
        first = first[:157] + "…"
    return f"En {label}: {first}"
