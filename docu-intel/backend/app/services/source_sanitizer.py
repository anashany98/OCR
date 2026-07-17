"""CR1 — Sanitize AI answer source references before persistence.

The problem: ``AIAnswerSource`` has a FK to ``document_blocks.id``.
When a document is reprocessed, its blocks may be deleted and
recreated, leaving stale ``block_id`` references. The INSERT then
violates the FK constraint, aborting the entire transaction — and
the user sees ``Sin fuentes`` even though the answer text was
already streamed.

The fix: validate each source reference before persisting. When a
``block_id`` is stale, set it to ``NULL`` and keep the rest of the
metadata (document_id, page_number, excerpt) so the answer remains
useful. A Prometheus counter tracks how often this happens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentBlock

logger = logging.getLogger("app.services.source_sanitizer")


@dataclass(frozen=True)
class SanitizedSource:
    """A source reference ready for safe DB persistence."""

    document_id: int | None
    page_number: int | None
    block_id: int | None
    relevance_score: float | None
    excerpt: str | None
    # True when the original block_id was stale and was set to None.
    degraded: bool = False


def sanitize_source_reference(
    db: Session,
    *,
    document_id: int | None,
    page_number: int | None,
    block_id: int | None,
    relevance_score: float | None,
    excerpt: str | None,
) -> SanitizedSource:
    """Validate a single source reference before DB persistence.

    If ``block_id`` is not None, verify it exists in
    ``document_blocks``. If it does not, set it to None and flag the
    source as degraded. The caller should increment the
    ``ai_source_stale_block_total`` metric when degraded is True.

    Sources with ``block_id=None`` from the start are passed through
    unchanged (they are not stale, they simply were never associated
    with a block).
    """
    if block_id is None:
        return SanitizedSource(
            document_id=document_id,
            page_number=page_number,
            block_id=None,
            relevance_score=relevance_score,
            excerpt=excerpt,
        )

    exists = db.scalar(select(DocumentBlock.id).where(DocumentBlock.id == block_id).limit(1))
    if exists is not None:
        return SanitizedSource(
            document_id=document_id,
            page_number=page_number,
            block_id=block_id,
            relevance_score=relevance_score,
            excerpt=excerpt,
        )

    logger.debug(
        "Stale block_id %s for document %s page %s — setting to NULL",
        block_id,
        document_id,
        page_number,
    )
    return SanitizedSource(
        document_id=document_id,
        page_number=page_number,
        block_id=None,
        relevance_score=relevance_score,
        excerpt=excerpt,
        degraded=True,
    )


def sanitize_sources_batch(
    db: Session,
    sources: list[dict],
) -> list[SanitizedSource]:
    """Sanitize a batch of source dicts (from ``sources_payload``).

    Each dict must have keys: document_id, page_number, block_id,
    relevance_score, excerpt. Returns a list of ``SanitizedSource``
    ready for ``AIAnswerSource`` insertion.
    """
    result: list[SanitizedSource] = []
    for src in sources:
        sanitized = sanitize_source_reference(
            db,
            document_id=src.get("document_id"),
            page_number=src.get("page_number"),
            block_id=src.get("block_id"),
            relevance_score=src.get("relevance_score"),
            excerpt=src.get("excerpt"),
        )
        result.append(sanitized)
        if sanitized.degraded:
            from app.services.metrics.rag import track_ai_source_stale_block

            track_ai_source_stale_block()
    return result
