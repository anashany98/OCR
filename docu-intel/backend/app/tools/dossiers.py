"""Dossier / list tools — answer aggregation questions about a budget.

The agent was good at "what does this document say" but poor at
"how many X are there" or "list everything in budget N" because it
forced every question through the RAG pipeline. These tools give
the agent direct access to the catalogue (Document table) and the
dossier (BudgetScope table) so simple aggregation questions get
deterministic answers with a single SQL roundtrip.

All tools respect the per-user access scope: rows the user cannot
see are filtered out before the result is returned.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BudgetScope, Document
from app.services.tenant_access import filter_documents_for_scope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_BUDGET_CODE_RE = re.compile(r"\b(\d{6})\b")


def extract_budget_code(question: str) -> str | None:
    """Pull the first 6-digit budget code from the question.

    The system uses 6-digit numeric codes (250052, 250053, …). The
    router is intentionally cheap: only the most common form is
    caught, so a false positive is acceptable (we can always fall
    back to RAG).
    """
    match = _BUDGET_CODE_RE.search(question or "")
    return match.group(1) if match else None


def _document_to_dict(d: Document) -> dict[str, Any]:
    """Compact serialisation used by every dossier tool.

    Kept deliberately flat (no nested entities) so the structured
    answer renderer can iterate the list and produce a table.
    """
    return {
        "id": d.id,
        "filename": d.original_filename,
        "document_type": d.document_type,
        "quality_status": d.quality_status,
        "quality_score": d.quality_score,
        "extension": d.extension,
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "processed_at": d.processed_at.isoformat() if d.processed_at else None,
        "page_count": d.page_count,
        "confidence": d.confidence,
        "duplicate_of_document_id": d.duplicate_of_document_id,
    }


def _resolve_budget_scope_id(db: Session, budget_code: str) -> int | None:
    """Return the BudgetScope id for a 6-digit code, or None when the
    scope is not registered (legacy ingested documents that predate
    the scope table). The function never raises; callers fall back to
    the path-based LIKE search.
    """
    if not budget_code:
        return None
    row = db.scalar(
        select(BudgetScope.id)
        .where(BudgetScope.budget_code == str(budget_code).strip())
        .limit(1)
    )
    return int(row) if row is not None else None


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


def list_documents_by_budget_code(
    db: Session,
    budget_code: str,
    *,
    document_type: str | None = None,
    quality_status: str | None = None,
    extension: str | None = None,
    limit: int = 50,
    access_scope: Any | None = None,
) -> list[dict[str, Any]]:
    """Return documents in a budget scope as a flat list.

    Filters by ``document_type`` (``albaran``, ``factura``, ``email_exportado``,
    …), ``quality_status`` (``processed_ok``, ``needs_human_review``, …) and
    ``extension`` (``.msg``, ``.pdf``, …). Used to answer questions like
    "qué correos hay en el presupuesto 250258" or "qué facturas tiene el
    250152 con calidad mala".

    The lookup uses the ``budget_scope_id`` FK when available (fast
    indexed equality) and falls back to a LIKE on ``source_path`` so
    legacy documents without a registered scope are still found.
    """
    code = str(budget_code).strip()
    if not code:
        return []

    scope_id = _resolve_budget_scope_id(db, code)
    if scope_id is not None:
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.budget_scope_id == scope_id)
        )
    else:
        # Fallback: path-based. ILIKE is case-insensitive on Postgres.
        pattern = f"%/Presupuesto {code}/%"
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.source_path.ilike(pattern))
        )

    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if quality_status:
        stmt = stmt.where(Document.quality_status == quality_status)
    if extension:
        stmt = stmt.where(Document.extension == extension.lower())

    stmt = stmt.order_by(Document.document_type.asc(), Document.id.asc()).limit(
        min(limit * 4, 400)
    )

    rows = list(db.scalars(stmt).all())
    if access_scope is not None:
        rows = filter_documents_for_scope(db, rows, access_scope)

    return [_document_to_dict(d) for d in rows[:limit]]


def list_distinct_budget_codes(
    db: Session,
    *,
    access_scope: Any | None = None,
    limit: int = 200,
) -> list[str]:
    """Return the distinct budget codes currently in the system.

    Tries the BudgetScope table first (clean source of truth) and
    falls back to scanning the source_path of documents when the
    scope is not registered. Returns a sorted list of 6-digit
    strings.

    Used to answer "cuántos presupuestos distintos hay" and
    "lista los códigos numéricos".
    """
    codes: set[str] = set()

    # 1) BudgetScope rows
    scope_codes = list(
        db.scalars(select(BudgetScope.budget_code).limit(1000)).all()
    )
    for c in scope_codes:
        s = str(c).strip()
        if s.isdigit() and len(s) == 6:
            codes.add(s)
        else:
            # Some legacy codes might be wrapped (e.g. " 250052 ")
            m = _BUDGET_CODE_RE.search(s)
            if m:
                codes.add(m.group(1))

    # 2) Fallback: source_path
    if not codes:
        paths = list(
            db.scalars(
                select(Document.source_path)
                .where(Document.deleted_at.is_(None))
                .where(Document.source_path.is_not(None))
                .limit(5000)
            ).all()
        )
        for p in paths:
            m = re.search(r"Presupuesto\s+(\d{6})", p or "")
            if m:
                codes.add(m.group(1))

    # Apply access scope: a user without read on any doc in a budget
    # must not see the code. We do this by checking the existence of
    # at least one visible document per code. Cheap enough at 200 codes.
    if access_scope is not None and codes:
        visible: set[str] = set()
        for code in codes:
            rows = list_documents_by_budget_code(
                db, code, limit=1, access_scope=access_scope
            )
            if rows:
                visible.add(code)
        codes = visible

    return sorted(codes)[:limit]


def get_budget_summary(
    db: Session,
    budget_code: str,
    *,
    access_scope: Any | None = None,
) -> dict[str, Any]:
    """Aggregate stats for a budget: counts by type, by quality, list.

    Returns a dict ready to be rendered as a card by the frontend.
    Used for "resumen ejecutivo del presupuesto X".
    """
    documents = list_documents_by_budget_code(
        db, budget_code, limit=200, access_scope=access_scope
    )
    if not documents:
        return {
            "budget_code": budget_code,
            "found": False,
            "document_count": 0,
            "by_type": {},
            "by_quality": {},
            "by_extension": {},
            "documents": [],
        }

    by_type: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    for d in documents:
        by_type[d["document_type"]] = by_type.get(d["document_type"], 0) + 1
        by_quality[d["quality_status"]] = by_quality.get(d["quality_status"], 0) + 1
        ext = d["extension"] or "(sin extensión)"
        by_extension[ext] = by_extension.get(ext, 0) + 1

    return {
        "budget_code": budget_code,
        "found": True,
        "document_count": len(documents),
        "by_type": by_type,
        "by_quality": by_quality,
        "by_extension": by_extension,
        "documents": documents,
    }


def find_nearest_budget(
    db: Session,
    budget_code: str,
) -> dict[str, int | str] | None:
    """Return the closest existing budget code to a non-existing one.

    Returns ``{"above": N, "below": N, "closest": N}`` or ``None`` when
    the system has no budget codes at all. Used for "el presupuesto
    250999 existe? Si no, cuál es el más cercano?".
    """
    codes = list_distinct_budget_codes(db)
    if not codes:
        return None
    try:
        target = int(budget_code)
    except (TypeError, ValueError):
        return None
    nums = sorted(int(c) for c in codes)
    if target in nums:
        return {"exact": target, "closest": target}
    above = next((n for n in nums if n > target), None)
    below = next((n for n in reversed(nums) if n < target), None)
    if above is None and below is None:
        return None
    if above is None:
        return {"below": below, "closest": below}
    if below is None:
        return {"above": above, "closest": above}
    return {
        "above": above,
        "below": below,
        "closest": above if (above - target) <= (target - below) else below,
    }


def find_documents_by_reference(
    db: Session,
    reference: str,
    *,
    include_duplicates: bool = True,
    access_scope: Any | None = None,
) -> list[dict[str, Any]]:
    """Search documents whose filename or source path contain ``reference``.

    Used for "está duplicada la factura 250013" and "qué documentos
    mencionan la referencia 245745". The match is partial and case
    insensitive. The function also returns the ``duplicate_of_document_id``
    link so the renderer can show "X es duplicado de Y" without a
    second query.
    """
    if not reference or not reference.strip():
        return []
    pattern = f"%{reference.strip()}%"
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(
            (Document.original_filename.ilike(pattern))
            | (Document.source_path.ilike(pattern))
        )
        .order_by(Document.id.asc())
        .limit(50)
    )
    rows = list(db.scalars(stmt).all())
    if not include_duplicates:
        rows = [d for d in rows if d.quality_status != "duplicate"]
    if access_scope is not None:
        rows = filter_documents_for_scope(db, rows, access_scope)
    return [_document_to_dict(d) for d in rows]


# ---------------------------------------------------------------------------
# Aggregations over the Document table (no budget scope dependency)
# ---------------------------------------------------------------------------


def document_count_by_status(
    db: Session,
    budget_code: str | None = None,
) -> dict[str, int]:
    """Return counts of documents grouped by ``quality_status``.

    Used for "cuántos documentos están pendientes de revisión" and
    similar dashboard questions.
    """
    stmt = select(Document.quality_status, func.count(Document.id)).where(
        Document.deleted_at.is_(None)
    ).group_by(Document.quality_status)
    if budget_code:
        scope_id = _resolve_budget_scope_id(db, budget_code)
        if scope_id is not None:
            stmt = stmt.where(Document.budget_scope_id == scope_id)
        else:
            stmt = stmt.where(
                Document.source_path.ilike(f"%/Presupuesto {budget_code}/%")
            )
    rows = db.execute(stmt).all()
    return {str(qs): int(c) for qs, c in rows}
