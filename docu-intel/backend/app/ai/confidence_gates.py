"""CTX-8 — Confidence gates and anti-hallucination rules.

The agent must not invent amounts when the OCR is bad, the document
is a duplicate, the type is unknown, or the extraction itself was
uncertain. The :func:`evaluate_confidence_gates` function returns a
small dict that the orchestrator uses to:

* skip the LLM call when a question about an amount would otherwise
  produce a fabricated number;
* render a list of amount candidates (when any are present) so the
  user can verify the answer themselves;
* add a human-readable warning to the prompt so the LLM knows it
  must be conservative.

The rules are intentionally coarse — they apply to "amount
questions" detected by the intent router. For other intents the
gates are advisory only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .context import ContextItem, LOW_OCR_CONFIDENCE_THRESHOLD
from .intent_router import (
    INTENT_BUDGET_LINES,
    INTENT_BUDGET_TOTAL,
    INTENT_DOCUMENT_SUMMARY,
    INTENT_INVOICED_AMOUNT,
    INTENT_PLAN_SUMMARY,
    INTENT_SHIPPING_COST,
    IntentClassification,
    classify_intent,
)


# Amount-style questions: intents that the user is most likely to
# expect a concrete number from. When the gate is open, the
# orchestrator refuses to invent the number.
AMOUNT_INTENTS: frozenset[str] = frozenset(
    {
        INTENT_BUDGET_TOTAL,
        INTENT_INVOICED_AMOUNT,
        INTENT_SHIPPING_COST,
    }
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateEvaluation:
    """The verdict for one assistant turn.

    Attributes:
        gates_open: list of human-readable gate names that blocked
            the response (empty = the answer is safe to produce).
        requires_amount: True when the user's question expects a
            concrete amount (so a gate must be respected).
        amount_candidates: list of small dicts the user can use to
            verify the answer manually. Each entry has ``label``,
            ``amount``, ``currency``, ``document`` and ``confidence``.
        reason: short human-readable summary of the gate.
    """

    gates_open: list[str] = field(default_factory=list)
    requires_amount: bool = False
    amount_candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    @property
    def is_blocked(self) -> bool:
        return self.requires_amount and bool(self.gates_open)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gates_open": list(self.gates_open),
            "requires_amount": self.requires_amount,
            "amount_candidates": list(self.amount_candidates),
            "reason": self.reason,
            "is_blocked": self.is_blocked,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_AMOUNT_RE = re.compile(
    r"""
    (?<![\w.,])
    (?:€|\$|eur(?:os?)?|usd|£)?
    \s*
    \d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?
    \s*
    (?:€|eur(?:os?)?|usd|\$|£)?
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _extract_amount_candidates(items: Iterable[ContextItem]) -> list[dict[str, Any]]:
    """Pull currency-shaped numbers from the context excerpts.

    Used to give the user a list of "amounts the OCR could see" so
    they can verify the answer themselves when the gate blocks the
    LLM from naming one of them.
    """
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        blob = item.excerpt or item.summary or ""
        if not blob:
            continue
        for match in _AMOUNT_RE.finditer(blob):
            raw = match.group(0).strip()
            if len(raw) < 3:
                continue
            key = (raw, item.document_filename or item.title or "")
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "amount": raw,
                    "document": item.document_filename or item.title or "",
                    "page": item.page_number,
                    "confidence": item.confidence,
                }
            )
    return candidates[:12]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_confidence_gates(
    *,
    question: str,
    context_items: list[ContextItem],
    resolved_document: dict | None = None,
) -> GateEvaluation:
    """Run the gates and return the verdict.

    The function is pure (no DB, no LLM). It is called by the
    orchestrator after the context has been built and before the LLM
    call so the LLM prompt can include the gate warnings.
    """
    intent_cls: IntentClassification = classify_intent(question)
    requires_amount = intent_cls.intent in AMOUNT_INTENTS
    gates_open: list[str] = []

    top = context_items[0] if context_items else None

    # Gate: low OCR confidence on the top item.
    if top is not None and _is_low_ocr(top):
        gates_open.append("ocr_baja_confianza")
    # Gate: status duplicate.
    if _has_resolved_meta(resolved_document, "status", "duplicate"):
        gates_open.append("documento_duplicado")
    # Gate: type unknown.
    if _has_resolved_meta(resolved_document, "document_type", "desconocido") or _has_resolved_meta(
        resolved_document, "document_type", "unknown"
    ):
        gates_open.append("tipo_documento_desconocido")
    # Gate: needs_review.
    if _has_resolved_meta(resolved_document, "status", "needs_review"):
        gates_open.append("necesita_revision")
    # Gate: no text at all.
    if top is not None and not (top.excerpt or top.summary or "").strip():
        gates_open.append("sin_texto_ocr")
    # Gate: top item is a very short text (likely garbage).
    if top is not None and _is_garbage_text(top):
        gates_open.append("texto_muy_corto")

    candidates = _extract_amount_candidates(context_items)

    reason = ""
    if gates_open:
        reason = (
            "No puedo confirmarlo con seguridad: "
            + ", ".join(gates_open)
            + "."
        )

    return GateEvaluation(
        gates_open=gates_open,
        requires_amount=requires_amount,
        amount_candidates=candidates,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_low_ocr(item: ContextItem) -> bool:
    if item.ocr_confidence is not None and item.ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD:
        return True
    if item.confidence is not None and item.confidence < LOW_OCR_CONFIDENCE_THRESHOLD:
        return True
    return False


def _is_garbage_text(item: ContextItem) -> bool:
    """A crude check for a chunk that is too short / mostly symbols."""
    text = (item.excerpt or item.summary or "").strip()
    if len(text) < 40:
        return True
    alnum = sum(1 for c in text if c.isalnum() or c.isspace())
    return alnum / max(len(text), 1) < 0.5


def _has_resolved_meta(
    resolved_document: dict | None, key: str, value: str
) -> bool:
    if not resolved_document:
        return False
    actual = resolved_document.get(key)
    if actual is None:
        return False
    return str(actual).lower() == value


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def gate_warning_prompt_line(evaluation: GateEvaluation) -> str | None:
    """One-line warning for the LLM prompt.

    Returns ``None`` when no warning is needed. The text is in
    Spanish, in the same prose style as the rest of the system
    prompt, so the LLM can quote it.
    """
    if not evaluation.gates_open:
        return None
    rules = {
        "ocr_baja_confianza": "El OCR del documento principal tiene baja confianza. No confirmes importes.",
        "documento_duplicado": "El documento es un duplicado sin extraccion propia. No inventes contenido.",
        "tipo_documento_desconocido": "El tipo de documento no esta clasificado todavia. No hagas suposiciones sobre su contenido.",
        "necesita_revision": "El documento esta marcado para revision humana. No confirmes datos sensibles.",
        "sin_texto_ocr": "No hay texto OCR extraido. No resumas contenido que no has visto.",
        "texto_muy_corto": "El texto extraido es muy corto. No extrapoles.",
    }
    bits = [rules.get(g, g) for g in evaluation.gates_open]
    return " ".join(bits)
