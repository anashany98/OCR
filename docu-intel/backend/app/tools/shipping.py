"""Shipping and delivery note tools for the AI agent.

Used to find delivery notes (albaranes) and shipping costs within
the active scope.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.search_service import _escape_ilike_wildcards

# Keywords that signal a shipping/transport cost. Kept in a module
# constant so tests can assert against it without importing the
# tools module.
SHIPPING_KEYWORDS: tuple[str, ...] = (
    "envio",
    "envío",
    "transporte",
    "portes",
    "flete",
    "fletes",
    "freight",
    "shipping",
    "logistica",
    "logística",
    "entrega",
)


def find_delivery_note_in_scope(
    db: Session,
    *,
    budget_number: str | None = None,
    folder_path: str | None = None,
    source_path_like: str | None = None,
) -> dict:
    """Search for a delivery note (albaran) inside the active scope.

    The search is by document_type (albaran / delivery_note) and by
    filename pattern (the words ``albaran``, ``albarán``, ``entrega``).
    The scope filter is mandatory: when no budget / folder hint is
    given, the function returns an empty list (refusing to look
    outside an active scope) so a follow-up like "dispones del albaran
    de entrega" can never silently jump to a different budget.

    The shape mirrors what the orchestrator needs::

        {
            "found": bool,
            "matches": [{"document_id", "filename", "source_path",
                         "page_number", "confidence", "score"}],
            "scope": "...",
        }
    """
    pattern = "%albaran%"
    candidates: list[Document] = []
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if source_path_like:
        # ``source_path_like`` is user-supplied (it can be a path
        # substring); escape the ILIKE wildcards so a user typing
        # ``%245`` or ``_foo`` does not get wildcard expansion.
        stmt = stmt.where(Document.source_path.ilike(_escape_ilike_wildcards(source_path_like)))
    elif folder_path:
        stmt = stmt.where(Document.source_path.ilike(f"%{_escape_ilike_wildcards(folder_path)}%"))
    elif budget_number:
        # ``budget_number`` is a number we look up in our own DB
        # (e.g. ``245745``); it is not user-typed text, so escaping is
        # not strictly required but we do it anyway for defense in
        # depth.
        stmt = stmt.where(
            Document.source_path.ilike(f"%Presupuesto {_escape_ilike_wildcards(budget_number)}%")
        )
    else:
        # No scope: refuse to guess.
        return {
            "found": False,
            "matches": [],
            "scope": None,
            "reason": "no se ha indicado ambito (presupuesto o carpeta)",
        }
    candidates = list(
        db.scalars(
            stmt.where(
                (Document.document_type.in_(["albaran", "delivery_note"]))
                | (Document.original_filename.ilike(pattern))
            )
            .order_by(Document.id.desc())
            .limit(10)
        ).all()
    )
    return {
        "found": bool(candidates),
        "scope": (
            f"Presupuesto {budget_number}" if budget_number else folder_path or source_path_like
        ),
        "matches": [
            {
                "document_id": d.id,
                "filename": d.original_filename,
                "source_path": d.source_path,
                "document_type": d.document_type,
                "status": d.status,
                "confidence": d.confidence,
            }
            for d in candidates
        ],
    }


def find_shipping_cost_in_scope(
    db: Session,
    *,
    budget_number: str | None = None,
    folder_path: str | None = None,
    source_path_like: str | None = None,
    limit: int = 5,
) -> dict:
    """Find the shipping cost inside the active scope.

    The search is restricted to documents in the scope and looks for
    the SHIPPING_KEYWORDS in chunk text + line descriptions. Returns
    a list of small dicts with the candidate amount, the document it
    came from, and the keyword that matched so the LLM can cite the
    evidence and the user can verify it.
    """
    if not (budget_number or folder_path or source_path_like):
        return {
            "found": False,
            "candidates": [],
            "scope": None,
            "reason": "no se ha indicado ambito (presupuesto o carpeta)",
        }
    like = (
        source_path_like
        or (f"%{_escape_ilike_wildcards(folder_path)}%" if folder_path else None)
        or f"%Presupuesto {_escape_ilike_wildcards(budget_number)}%"
    )
    # ILIKE any of the shipping keywords against chunk_text.
    keyword_ors = [DocumentChunk.chunk_text.ilike(f"%{kw}%") for kw in SHIPPING_KEYWORDS]
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.deleted_at.is_(None))
        .where(Document.source_path.ilike(_escape_ilike_wildcards(like)))
        .where(or_(*keyword_ors))
        .order_by(DocumentChunk.confidence.desc().nullslast())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    candidates: list[dict] = []
    for chunk, doc in rows:
        if not chunk.chunk_text:
            continue
        candidates.append(
            {
                "document_id": doc.id,
                "filename": doc.original_filename,
                "source_path": doc.source_path,
                "page_number": chunk.page_number,
                "excerpt": (chunk.chunk_text or "")[:240],
                "chunk_confidence": chunk.confidence,
                "document_confidence": doc.confidence,
            }
        )
    return {
        "found": bool(candidates),
        "scope": (
            f"Presupuesto {budget_number}" if budget_number else folder_path or source_path_like
        ),
        "candidates": candidates,
    }
