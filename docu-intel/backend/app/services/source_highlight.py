"""R4 — Backend support for highlighting cited sources in the document viewer.

When the AI chat cites a source (e.g. "según el presupuesto
245745, página 2"), the user should be able to click on it and
see the document opened at that page with the cited block
highlighted.

This module provides the backend query that the frontend needs:
given an ``answer_id`` and a ``source_index``, return the
``document_id``, ``page_number``, ``block_id`` and the
bounding box of the cited block so the frontend can scroll to
it and draw a highlight overlay.

The module is **read-only** (no mutations) and **fail-safe**:
any error returns ``None`` so the caller can decide whether to
show a "source not available" message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AIAnswer, AIAnswerSource, DocumentBlock

logger = logging.getLogger("app.services.source_highlight")


@dataclass(frozen=True)
class SourceHighlight:
    """The information the frontend needs to highlight a cited
    source in the document viewer.

    Attributes:
        document_id: the document to open.
        page_number: the page to scroll to.
        block_id: the specific block to highlight (may be
            ``None`` when the source is a chunk, not a block).
        bbox: the bounding box ``(x0, y0, x1, y1)`` of the
            block in PDF coordinates (points). ``None`` when
            the block has no bbox.
        excerpt: the text of the cited source (for display in
            the highlight tooltip).
    """

    document_id: int
    page_number: int | None
    block_id: int | None
    bbox: tuple[float, float, float, float] | None
    excerpt: str | None


def get_source_highlight(
    db: Session,
    *,
    answer_id: int,
    source_index: int = 0,
) -> SourceHighlight | None:
    """Return the highlight information for a cited source.

    Args:
        db: SQLAlchemy session.
        answer_id: the ``AIAnswer.id`` that contains the source.
        source_index: 0-based index into the answer's sources
            list (the first source cited is index 0).

    Returns:
        :class:`SourceHighlight` or ``None`` when the source
        does not exist or the answer does not belong to the
        current user.
    """
    answer = db.get(AIAnswer, answer_id)
    if answer is None:
        return None

    sources = list(
        db.query(AIAnswerSource)
        .filter(AIAnswerSource.answer_id == answer_id)
        .order_by(AIAnswerSource.id.asc())
        .all()
    )
    if source_index < 0 or source_index >= len(sources):
        return None

    source = sources[source_index]
    bbox: tuple[float, float, float, float] | None = None

    # If the source has a block_id, look up the block's bbox.
    if source.block_id is not None:
        block = db.get(DocumentBlock, source.block_id)
        if block is not None and all(
            v is not None for v in (block.bbox_x1, block.bbox_y1, block.bbox_x2, block.bbox_y2)
        ):
            bbox = (
                float(block.bbox_x1),
                float(block.bbox_y1),
                float(block.bbox_x2),
                float(block.bbox_y2),
            )

    return SourceHighlight(
        document_id=source.document_id or 0,
        page_number=source.page_number,
        block_id=source.block_id,
        bbox=bbox,
        excerpt=source.excerpt,
    )


__all__ = [
    "SourceHighlight",
    "get_source_highlight",
]
