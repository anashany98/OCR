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
    "ñ",
    "á",
    "é",
    "í",
    "ó",
    "ú",
    "ü",
    "¿",
    "¡",
    " el ",
    " la ",
    " los ",
    " las ",
    " de ",
    " que ",
    " con ",
    " para ",
    " por ",
    " según ",
    " documento",
    " presupuesto",
    " pedido",
    " proveedor",
    " importe",
    " no he ",
    " no hay ",
    " he encontrado",
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


# Regex for plausible document numbers in the answer. We try to be
# strict enough to avoid false positives (page numbers, year stamps)
# but loose enough to catch the common formats the suppliers use:
#   ``2026/143``, ``F-2026-044``, ``P-2026-007``, ``PV26-020921``,
#   ``B1234567``, ``pedido 442403``. Each match is normalised to
# alphanumeric-only lower-case before the lookup, so hyphen / slash
# separators are transparent to the comparison.
_DOC_NUMBER_PATTERN = re.compile(
    r"""
    \b
    (?:
        # Prefixed: F-2026-044, P-2026-007, PV26-020921, F26-001
        (?:[A-Z]{1,4}[\-_]?\d{2,4}[\-_]?\d{1,6})
        |
        # Slashed or dashed: 2026/143, 2026-143, 2026.143
        \d{4}[/\-.]?\d{2,6}
        |
        # Pure long numeric: 442403, 2026044
        \d{5,8}
    )
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Regex for plausible currency amounts. Captures the value so we
# can normalise it the same way for both context and answer.
# Covers es-ES (1.234,56 EUR) and en-US (1,234.56 USD) shapes.
_AMOUNT_PATTERN = re.compile(
    r"""
    (?<![\w.,])                   # not preceded by digit/dot/comma
    (?:€|\$|eur(?:os?)?|usd|£)?   # optional currency symbol
    \s*
    \d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?  # 1.234,56 / 1,234.56 / 1234,5
    \s*
    (?:€|eur(?:os?)?|usd|\$|£)?   # optional trailing currency
    (?![\w.,])                    # not followed by digit/dot/comma
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _normalise_amount(raw: str) -> str | None:
    """Canonical form for an amount: digits only, lower-case.

    Strips currency symbols, thousands separators and the trailing
    decimal. ``"1.234,56 EUR"`` and ``"1234,56 EUR"`` and
    ``"1,234.56"`` all collapse to ``"123456"``. Returns None when
    the amount is too short to be meaningful (less than 2 digits).
    """
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.,]", "", raw)
    if not cleaned:
        return None
    # Decide separator role: last separator is decimal, the rest are
    # thousands. This matches both es-ES and en-US for values with
    # both separators. For a single separator, treat it as decimal
    # when the part after it has 1-2 digits (typical currency case).
    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")
    if last_dot == -1 and last_comma == -1:
        digits = cleaned
    elif last_dot > last_comma:
        # dot is decimal; commas are thousands.
        digits = cleaned.replace(",", "")
    elif last_comma > last_dot:
        # comma is decimal; dots are thousands.
        digits = cleaned.replace(".", "").replace(",", ".")
    else:
        digits = cleaned
    digits = digits.replace(".", "").replace(",", "")
    if len(digits) < 2:
        return None
    return digits


def _normalise_doc_number(raw: str) -> str:
    """Canonical form for a document number: alphanumeric, no
    separators, lower-case. ``"F-2026-044"``, ``"F 2026 044"`` and
    ``"f2026044"`` all collapse to ``"f2026044"``.
    """
    return re.sub(r"[\s\-_/.]", "", raw).lower()


def _extract_known_doc_numbers(context_items: list[ContextItem]) -> set[str]:
    """Collect every document number that appears in the grounded
    context (summary, excerpt, title). Returns the normalised
    set so the answer's numbers can be checked against it."""
    known: set[str] = set()
    for item in context_items:
        for blob in (item.summary, item.excerpt, item.title):
            if not blob:
                continue
            for match in _DOC_NUMBER_PATTERN.finditer(blob):
                normalised = _normalise_doc_number(match.group(0))
                if len(normalised) >= 4:
                    known.add(normalised)
    return known


def _extract_known_amounts(context_items: list[ContextItem]) -> set[str]:
    """Collect every currency amount present in the context."""
    known: set[str] = set()
    for item in context_items:
        for blob in (item.summary, item.excerpt):
            if not blob:
                continue
            for match in _AMOUNT_PATTERN.finditer(blob):
                normalised = _normalise_amount(match.group(0))
                if normalised:
                    known.add(normalised)
    return known


def _filename_is_known(ref: str, known: set[str]) -> bool:
    """Return True if ``ref`` plausibly matches any of the known
    filenames or basenames. The previous loose ``k in ref or ref in k``
    check caused false positives like ``"FACTURA"`` matching
    ``"FACTURAS.pdf"``; the new check is exact on the full name
    *or* on the stem (basename without extension).
    """
    ref_low = ref.lower()
    if ref_low in known:
        return True
    stem = ref_low.rsplit(".", 1)[0] if "." in ref_low else ref_low
    return stem in known


def response_fabricates_documents(answer: str, context_items: list[ContextItem]) -> bool:
    """Reject the response if it fabricates a document reference,
    document number, or amount that does not exist in the context.

    Three sub-checks, all best-effort (any one of them rejecting the
    answer is enough):

    1. **Filenames** — any ``*.pdf`` / ``*.docx`` / ``*.msg`` reference
       in the answer must match (by full name or by basename) one of
       the documents in the context.
    2. **Document numbers** — plausible budget / order / invoice
       numbers (e.g. ``F-2026-044``, ``2026/143``) mentioned in the
       answer must appear in the context. The previous version did
       not check this, so a hallucinated invoice number slipped
       through whenever the LLM happened to mention one.
    3. **Amounts** — currency amounts in the answer (``241,00 EUR``,
       ``1.234,56 €``) must appear in the context. This catches the
       common LLM failure mode of inventing totals.

    The function stays cheap and pure: it never reads the DB and
    never makes an LLM call, so it can run on every AI response.
    """
    if not context_items:
        return False

    # 1) Filenames
    known_filenames: set[str] = set()
    for item in context_items:
        for name in (item.document_filename, item.title):
            if name:
                known_filenames.add(name.lower())
                stem = name.rsplit(".", 1)[0].lower() if "." in name else name.lower()
                known_filenames.add(stem)
    found_refs = re.findall(
        r"[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|png|jpe?g|tiff?)\b",
        answer,
        flags=re.IGNORECASE,
    )
    for ref in found_refs:
        if not _filename_is_known(ref, known_filenames):
            return True

    # 2) Document numbers
    known_numbers = _extract_known_doc_numbers(context_items)
    if known_numbers:
        for match in _DOC_NUMBER_PATTERN.finditer(answer):
            normalised = _normalise_doc_number(match.group(0))
            if len(normalised) < 4:
                continue
            if normalised not in known_numbers:
                return True

    # 3) Amounts
    known_amounts = _extract_known_amounts(context_items)
    if known_amounts:
        for match in _AMOUNT_PATTERN.finditer(answer):
            normalised = _normalise_amount(match.group(0))
            if not normalised or normalised in known_amounts:
                continue
            # Only flag amounts that look like currency-shaped values
            # (>= 2 digits and <= 9 digits, optional decimal in the
            # original). Sub-2-digit mentions like "10" or "1" are
            # too noisy and would over-trigger.
            if len(normalised) <= 9:
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
    has_budget = any(
        "presupuesto:" in it.summary.lower() or "presupuest" in it.title.lower()
        for it in context_items
    )
    has_order = any(
        "pedido" in it.summary.lower() or "pedido" in it.title.lower() for it in context_items
    )
    has_invoice = any(
        "factura" in it.summary.lower() or "factura" in it.title.lower() for it in context_items
    )
    has_aggregate = any("agregado" in it.title.lower() for it in context_items)

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
    " y ",
    " y la",
    " y las",
    " y los",
    " y el",
    " y del",
    " y de la",
    "que pasa con",
    "qué pasa con",
    "del mismo",
    "de la misma",
    "de ese",
    "de esa",
    "esos mismos",
    "esas mismas",
    "tambien",
    "también",
    "ahora dime",
    "y cuanto",
    "y cuántos",
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
