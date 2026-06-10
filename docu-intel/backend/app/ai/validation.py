"""Output validation, language detection, follow-ups, and memory helpers.

The LLM call returns text. Before we trust that text we run it
through three gates, in order:

1. **Language gate** (``_response_looks_spanish``): if the user
   asked in Spanish and the model answered in English, we drop
   the answer and fall back to the grounded response.
2. **Hallucination gate** (``_response_fabricates_documents``):
   if the answer mentions a filename that does not exist in the
   context, we drop the answer.
3. **Section gate** (``_has_required_sections``): kept as a stub
   for backward compatibility; the new system prompt tells the
   model NOT to use rigid sections, so we no longer gate on them.

Two adjacent concerns live in this module because they share the
same data: **conversation memory** (we read previous
``AIAnswer`` rows to resolve follow-up pronouns) and
**follow-up suggestions** (we produce 2-3 candidate questions
based on what we just answered). Both are pure-Python helpers
with no LLM call, which is the whole point of having them here:
they stay cheap and predictable.
"""
from __future__ import annotations

import json
import re
import unicodedata

from langdetect import DetectorFactory, LangDetectException, detect_langs
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AIAnswer, AIQuestion, User

from .context import ContextItem


# ---------------------------------------------------------------------------
# Module-level setup
# ---------------------------------------------------------------------------

# ``DetectorFactory.seed = 0`` makes langdetect reproducible.
DetectorFactory.seed = 0


# Spanish-specific characters and common Spanish function words. Used
# only as a fallback for very short or ambiguous text where langdetect
# has low signal.
_SPANISH_HINTS = (
    "ñ", "á", "é", "í", "ó", "ú", "ü", "¿", "¡",
    " el ", " la ", " los ", " las ", " de ", " que ",
    " con ", " para ", " por ", " según ", " documento",
    " presupuesto", " pedido", " proveedor", " importe",
    " no he ", " no hay ", " he encontrado",
)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def response_looks_spanish(answer: str) -> bool:
    """True when ``answer`` is plausibly in Spanish.

    Layered detection:
    1. If the text contains a Spanish diacritic, accept immediately.
    2. If langdetect says it's Spanish with prob >= 0.55, accept.
    3. If langdetect says it's NOT Spanish with prob >= 0.75, reject.
    4. Fallback: count common Spanish function words; accept
       when there are at least 2 hits.
    """
    if not answer or not answer.strip():
        return False
    if any(ch in answer for ch in "ñáéíóúü¿¡"):
        return True
    detected = _detect_language(answer)
    if detected:
        language, probability = detected
        if language == "es" and probability >= 0.55:
            return True
        if language != "es" and probability >= 0.75:
            return False
    lowered = " " + answer.lower() + " "
    hint_count = sum(1 for hint in _SPANISH_HINTS if hint in lowered)
    return hint_count >= 2


def question_is_spanish(question: str) -> bool:
    """True when ``question`` is plausibly in Spanish. Same
    heuristic as :func:`response_looks_spanish` but the
    thresholds are slightly stricter (we want to be sure the
    user really did ask in Spanish before rejecting a non-Spanish
    answer)."""
    if not question or not question.strip():
        return False
    if any(ch in question for ch in "ñáéíóúü¿¡"):
        return True
    detected = _detect_language(question)
    if detected:
        language, probability = detected
        if language == "es" and probability >= 0.55:
            return True
        if language != "es" and probability >= 0.85:
            return False
    lowered = " " + question.lower() + " "
    return any(hint in lowered for hint in (" el ", " la ", " los ", " las ", " de ", " que "))


def _detect_language(text: str) -> tuple[str, float] | None:
    """Wrap :func:`langdetect.detect_langs` with a length floor and
    exception handling. Returns the top candidate as ``(lang, prob)``
    or ``None`` when the text is too short or the detector gives up."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) < 12:
        return None
    try:
        candidates = detect_langs(cleaned)
    except LangDetectException:
        return None
    if not candidates:
        return None
    best = candidates[0]
    return best.lang, float(best.prob)


# ---------------------------------------------------------------------------
# Hallucination gate
# ---------------------------------------------------------------------------


def response_fabricates_documents(answer: str, context_items: list[ContextItem]) -> bool:
    """Reject the response if it mentions a plausible-looking filename
    that is not in the provided context (e.g. ``pres_cliente_xyz.pdf``).
    """
    if not context_items:
        return False
    # Build a set of normalised filenames from the context.
    known: set[str] = set()
    for item in context_items:
        for name in (item.document_filename, item.title):
            if name:
                known.add(name.lower())
                # Also keep the basename without extension.
                stem = name.rsplit(".", 1)[0].lower() if "." in name else name.lower()
                known.add(stem)
    # Look for any *.pdf / *.msg / *.docx reference in the response.
    found_refs = re.findall(
        r"[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|png|jpe?g|tiff?)\b", answer, flags=re.IGNORECASE
    )
    for ref in found_refs:
        ref_low = ref.lower()
        if not any(k in ref_low or ref_low in k for k in known):
            return True
    return False


def has_required_sections(answer: str) -> bool:
    """Legacy check kept for backward compatibility. The new system
    prompt explicitly tells the LLM NOT to use rigid sections, so
    we don't gate on them anymore. Kept as a stub so older imports
    do not break.
    """
    return True


# ---------------------------------------------------------------------------
# Follow-up suggestions
# ---------------------------------------------------------------------------


def suggest_followups(
    question: str,
    resolved_doc_id: int | None,
    context_items: list[ContextItem],
) -> list[str]:
    """Generate 2-3 follow-up question suggestions based on the
    resolved document. We do this locally (no LLM call) so the cost
    stays negligible and the suggestions appear immediately when
    the response lands."""
    suggestions: list[str] = []
    if not context_items:
        return suggestions

    # Detect entity types from the context (no DB needed: we already
    # gathered the items and their summaries carry the relation labels).
    has_budget = any("presupuesto:" in it.summary.lower() or "presupuest" in it.title.lower() for it in context_items)
    has_order = any("pedido" in it.summary.lower() or "pedido" in it.title.lower() for it in context_items)
    has_invoice = any("factura" in it.summary.lower() or "factura" in it.title.lower() for it in context_items)
    has_aggregate = any("agregado" in it.title.lower() for it in context_items)
    relations = [it.summary for it in context_items if " → " in it.summary or "En la misma" in it.summary or "derivado" in it.summary or "paga" in it.summary or "origina" in it.summary]

    if resolved_doc_id is not None:
        if has_budget:
            suggestions.append("¿Cuánto se ha facturado ya de este presupuesto?")
            suggestions.append("¿Qué lineas tiene este presupuesto?")
        if has_order:
            suggestions.append("¿Cual es el importe total de este pedido con sus lineas?")
            suggestions.append("¿Hay factura que pague este pedido?")
        if has_invoice:
            suggestions.append("¿Que pedido origino esta factura?")
        if has_aggregate:
            suggestions.append("¿Podrias desglosarlo por proveedor?")
            suggestions.append("¿Y si lo limito al ultimo trimestre?")
        if not suggestions:
            suggestions.append("¿Que otros documentos hay en la misma carpeta?")
            suggestions.append("¿Hay mas detalles sobre el contenido?")
    else:
        normalized = _normalize(question)
        if has_aggregate or "total" in normalized or "cuanto" in normalized:
            suggestions.append("¿Podrias desglosarlo por proveedor?")
            suggestions.append("¿Y si lo limito al ultimo trimestre?")
        elif "presupuest" in normalized:
            suggestions.append("¿Que pedidos estan pendientes de facturar?")
            suggestions.append("¿Cuanto suman los presupuestos aceptados?")
        elif "pedido" in normalized:
            suggestions.append("¿Que proveedor tiene mas pedidos en curso?")
        else:
            suggestions.append("¿Cuales son los ultimos presupuestos aceptados?")

    # Deduplicate and cap at 3.
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
        if len(out) >= 3:
            break
    return out


# ---------------------------------------------------------------------------
# Conversation memory
# ---------------------------------------------------------------------------


# Heuristics: short follow-up questions that need context from the prior turn.
_FOLLOWUP_HINTS = (
    " y ", " y la", " y las", " y los", " y el", " y del", " y de la",
    "que pasa con", "qué pasa con", "del mismo", "de la misma",
    "de ese", "de esa", "esos mismos", "esas mismas",
    "tambien", "también", "ahora dime", "y cuanto", "y cuántos",
)


def looks_like_followup(question: str) -> bool:
    """Return True if the question is short and looks like a follow-up
    that needs context from the previous turn."""
    q = (question or "").strip().lower()
    if len(q) > 110:
        return False
    if not q:
        return False
    return any(h in q for h in _FOLLOWUP_HINTS)


def build_memory_block(db: Session, user: User, question: str, limit: int = 3) -> str | None:
    """For short follow-up questions, pull the last ``limit``
    ``AIAnswer`` rows for the user and summarise the entities they
    referenced. This lets the LLM resolve pronouns like
    'y las facturas?' to the specific presupuesto / pedido that
    the previous turn was about.

    Returns ``None`` when the question does not look like a
    follow-up, when the user has no prior turns, or when no prior
    turn yielded any entity we can extract.
    """
    if not looks_like_followup(question):
        return None
    recent = list(
        db.scalars(
            select(AIAnswer)
            .join(AIQuestion, AIQuestion.id == AIAnswer.question_id)
            .where(AIQuestion.user_id == user.id)
            .order_by(AIAnswer.id.desc())
            .limit(limit)
        ).all()
    )
    if not recent:
        return None

    lines: list[str] = ["En los turnos anteriores de esta conversacion se mencionaron:"]
    for ans in reversed(recent):  # chronological order
        snippet = ans.answer.strip().split("\n")[0][:200] if ans.answer else ""
        entities: list[str] = []
        if ans.resolved_document_json:
            try:
                payload = json.loads(ans.resolved_document_json)
                doc = (payload or {}).get("document") or {}
                ent = doc.get("entities") or {}
                if ent.get("budget"):
                    b = ent["budget"]
                    if b.get("number"):
                        entities.append(f"presupuesto {b['number']}")
                    if b.get("client"):
                        entities.append(f"cliente {b['client']}")
                if ent.get("order"):
                    o = ent["order"]
                    if o.get("number"):
                        entities.append(f"pedido {o['number']}")
                    if o.get("supplier"):
                        entities.append(f"proveedor {o['supplier']}")
                if ent.get("invoice"):
                    i = ent["invoice"]
                    if i.get("number"):
                        entities.append(f"factura {i['number']}")
                if ent.get("plan"):
                    p = ent["plan"]
                    if p.get("project_name"):
                        entities.append(f"proyecto {p['project_name']}")
                if doc.get("filename"):
                    entities.append(f"archivo {doc['filename']}")
            except Exception:
                pass
        if entities:
            lines.append("- " + ", ".join(entities))
        elif snippet:
            lines.append(f"- (resumen) {snippet}")
    if len(lines) == 1:
        return None
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared text helpers (also imported by tools.py)
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase + strip accents for keyword matching. The original
    casing/accented text is preserved in the LLM prompt; this is
    only used for the cheap, in-Python keyword checks."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")
