"""FASE 6.1: did-you-mean suggestions when no answer context found.

Searches for documents with similar names/numbers to the user's
question and suggests them as alternatives.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Document

logger = logging.getLogger("app.ai.did_you_mean")


def suggest_similar_documents(db: Session, question: str) -> str | None:
    """Search for documents similar to the user's question.

    Returns a suggestion string with up to 3 document names, or None
    if no similar documents are found.
    """
    # Extract potential document numbers from the question
    numbers = re.findall(r"\b(\d{4,8})\b", question)
    if not numbers:
        return None

    # Search for documents with similar numbers in filename
    conditions = []
    for num in numbers[:3]:
        conditions.append(Document.original_filename.ilike(f"%{num}%"))

    if not conditions:
        return None

    try:
        docs = list(
            db.scalars(
                select(Document)
                .where(Document.deleted_at.is_(None))
                .where(or_(*conditions))
                .limit(5)
            ).all()
        )
    except Exception as exc:
        logger.debug("did-you-mean query failed: %s", exc)
        return None

    if not docs:
        return None

    # Build suggestion
    suggestions = []
    for doc in docs[:3]:
        name = doc.original_filename or f"Documento #{doc.id}"
        suggestions.append(f"- {name}")

    return (
        "No encontre resultados para tu pregunta, pero encontre "
        "documentos similares:\n" + "\n".join(suggestions) + "\n"
        "¿Te refieres a alguno de estos?"
    )
