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
_AMOUNT_IN_SUMMARY = re.compile(r"-\s*([0-9][0-9.,]*\s+[A-Z]{3})\s*-")


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
    if not can_view_prices or not _AMOUNT_QUESTION.search(question):
        return None
    for item in context_items:
        if item.document_id is None or (
            item.confidence is not None and item.confidence < 0.7
        ):
            continue
        match = _AMOUNT_IN_SUMMARY.search(item.summary or "")
        if not match:
            continue
        label = item.document_filename or item.title.replace("[Estructurado] ", "")
        return StructuredAnswerDecision(
            answer=f"El importe total es {match.group(1)} segun {label}.",
            document_id=item.document_id,
            filename=item.document_filename,
            page_number=item.page_number,
        )
    return None
