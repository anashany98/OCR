"""CR4 — Exact document search by identifier.

Search for documents by exact identifiers (budget numbers, order
numbers, document IDs, CIF/NIF, references, etc.) across all content
stores. This search has priority over semantic search: when it finds
a unique authorized match, it sets ``resolved_doc_id``.

The search normalizes separators, prefixes, and leading zeros but
preserves the original value so the caller can display it.

For numeric identifiers, word-boundary regex prevents partial matches
(e.g. ``26002`` should NOT match ``260025``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentBlock,
    DocumentChunk,
    DocumentEntity,
    DocumentPage,
)

logger = logging.getLogger("app.services.exact_document_search")


@dataclass
class ExactMatch:
    """A single exact match result."""

    document_id: int
    original_filename: str
    document_type: str
    source_path: str | None
    matched_in: str  # e.g. "page_text", "block_text", "entity", "filename"
    matched_value: str  # the actual matched text
    page_number: int | None = None


# ---------------------------------------------------------------------------
# Identifier detection
# ---------------------------------------------------------------------------

# Patterns for detecting identifiers in the question. Each entry is
# (regex, identifier_kind, normalized_form).
# The patterns are applied to the normalized (lowered, accent-stripped)
# question text.

_IDENTIFIER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Budget number: "presupuesto 260025", "presup. 260025", "P-260025"
    (re.compile(r"(?:presup(?:uesto)?|presup\.)\s*(?:n[°oº]?\s*)?(\d[\d\.\-\/\s]{2,})", re.I), "budget"),
    # Order number: "pedido 12345", "orden 12345", "order 12345"
    (re.compile(r"(?:pedido|orden(?:\s+de\s+trabajo)?|order)\s*(?:n[°oº]?\s*)?(\d[\d\.\-\/\s]{2,})", re.I), "order"),
    # Invoice number: "factura F-2025-001", "invoice INV-001"
    (re.compile(r"(?:factura|invoice)\s*(?:n[°oº]?\s*)?([A-Z]?\-?[\d\.\-\/\s]{2,})", re.I), "invoice"),
    # Delivery note: "albaran 12345"
    (re.compile(r"(?:albar(?:an|én))\s*(?:n[°oº]?\s*)?(\d[\d\.\-\/\s]{2,})", re.I), "delivery_note"),
    # CIF/NIF: "CIF B12345678", "NIF 12345678Z"
    (re.compile(r"(?:CIF|NIF|cif|nif)\s*([A-Z]?\d{5,9}[A-Z]?)", re.I), "tax_id"),
    # Reference: "referencia REF-12345", "ref. 12345"
    (re.compile(r"(?:referencia?|ref\.?)\s*([A-Z]?\-?[\w\.\-\/]{2,})", re.I), "reference"),
    # Generic number in quotes or after "numero": "numero 260025", "nº 260025"
    (re.compile(r"(?:n[°oº]|numero|num(?:ero)?)\s*[:\s]?\s*(\d[\d\.\-\/\s]{2,})", re.I), "document_number"),
]


def _normalize_number(value: str) -> str:
    """Normalize a numeric identifier by removing separators and
    common prefixes, but preserving the core number."""
    # Remove common separators
    normalized = re.sub(r"[\s\.\-\/]", "", value)
    # Remove leading zeros but keep at least one digit
    normalized = normalized.lstrip("0") or "0"
    return normalized


def _make_exact_pattern(value: str) -> str:
    """Create a SQL-safe ILIKE pattern for exact word-boundary match.

    Uses word boundaries to prevent partial matches. For the number
    ``260025``, this creates ``% 260025 %`` which matches ``260025``
    as a standalone token but NOT ``26002`` or ``2600250``.
    """
    # Escape SQL wildcards
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    # Word boundary using spaces/punctuation
    return f"% {escaped} %"


def _make_boundary_pattern(value: str) -> str:
    """Create a pattern that matches the value with word boundaries.

    This is more flexible than _make_exact_pattern: it allows the
    value to appear at the start/end of text, or surrounded by
    non-alphanumeric characters.
    """
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _contains_exact_number(text: str | None, normalized: str) -> bool:
    """Return whether ``normalized`` occurs as a complete numeric identifier.

    SQL ``ILIKE '%123%'`` is deliberately only a cheap pre-filter.  It must
    not decide the match because it would turn ``250398`` into a hit for
    ``12503980``.  Separators used in document numbers are accepted and
    leading zeros remain equivalent to their unpadded form.
    """
    if not text or not normalized:
        return False
    separated_digits = r"[\s.\-/]*".join(re.escape(digit) for digit in normalized)
    return re.search(rf"(?<!\d)0*{separated_digits}(?!\d)", text) is not None


def _contains_exact_phrase(text: str | None, phrase: str) -> bool:
    """Return whether a normalized literal phrase occurs in ``text``.

    This is intentionally lexical, not fuzzy: a query for ``Hostal Anibal``
    must never be satisfied by ``Hostal Anidac`` merely because semantic
    retrieval considers both strings similar.
    """
    if not text or not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, flags=re.IGNORECASE) is not None


# ---------------------------------------------------------------------------
# Search functions
# ---------------------------------------------------------------------------


def detect_identifiers(question: str) -> list[tuple[str, str]]:
    """Detect identifiers in the question.

    Returns a list of ``(kind, value)`` tuples where ``kind`` is the
    identifier type and ``value`` is the extracted raw value.
    """
    results: list[tuple[str, str]] = []
    for pattern, kind in _IDENTIFIER_PATTERNS:
        for match in pattern.finditer(question):
            # Get the last capturing group (the number/value)
            groups = match.groups()
            if groups:
                value = groups[-1].strip()
                if value and len(value) >= 2:
                    results.append((kind, value))
    return results


def search_exact_by_number(
    db: Session,
    *,
    number: str,
    kind: str = "generic",
    limit: int = 10,
    access_scope=None,
) -> list[ExactMatch]:
    """Search for documents containing an exact number match.

    Searches across:
    1. Document entities (budget_number, order_number, etc.)
    2. DocumentPage.text
    3. DocumentBlock.text
    4. DocumentChunk.chunk_text
    5. Document.original_filename
    6. Document.source_path

    Returns matches sorted by relevance (entities first, then pages,
    then blocks, then chunks, then filename).  A scope is mandatory for
    retrieval: callers without one receive no results.  This is deliberate
    deny-by-default behaviour, not a post-query presentation filter.
    """
    if access_scope is None:
        logger.warning("exact_search_without_access_scope kind=%s", kind)
        return []
    normalized = _normalize_number(number)
    matches: list[ExactMatch] = []
    seen_doc_ids: set[int] = set()

    # 1. Search entities first (highest confidence)
    for match in _search_entities(
        db, normalized=normalized, kind=kind, limit=limit, access_scope=access_scope
    ):
        if match.document_id not in seen_doc_ids:
            matches.append(match)
            seen_doc_ids.add(match.document_id)

    # 2. Search page text
    for match in _search_page_text(
        db, normalized=normalized, limit=limit, access_scope=access_scope
    ):
        if match.document_id not in seen_doc_ids:
            matches.append(match)
            seen_doc_ids.add(match.document_id)

    # 3. Search block text
    for match in _search_block_text(
        db, normalized=normalized, limit=limit, access_scope=access_scope
    ):
        if match.document_id not in seen_doc_ids:
            matches.append(match)
            seen_doc_ids.add(match.document_id)

    # 4. Search chunk text
    for match in _search_chunk_text(
        db, normalized=normalized, limit=limit, access_scope=access_scope
    ):
        if match.document_id not in seen_doc_ids:
            matches.append(match)
            seen_doc_ids.add(match.document_id)

    # 5. Search filename and source_path
    for match in _search_filename(
        db, normalized=normalized, number=number, limit=limit, access_scope=access_scope
    ):
        if match.document_id not in seen_doc_ids:
            matches.append(match)
            seen_doc_ids.add(match.document_id)

    return matches[:limit]


def search_exact_phrase(
    db: Session,
    *,
    phrase: str,
    limit: int = 10,
    access_scope=None,
) -> list[ExactMatch]:
    """Search an explicitly named subject by literal phrase.

    This is the companion to numeric exact search for names such as
    ``Hostal Anibal``.  It searches filenames, source paths, extracted entity
    values and OCR/chunk text, but only returns a document when the complete
    literal phrase is present.  Access predicates are applied before content
    is returned, matching :func:`search_exact_by_number`'s deny-by-default
    contract.
    """
    phrase = " ".join((phrase or "").split())
    if len(phrase) < 3:
        return []
    if access_scope is None:
        logger.warning("exact_phrase_search_without_access_scope")
        return []

    escaped = phrase.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    candidates: list[tuple[str, object, int | None]] = []

    entity_rows = db.execute(
        _apply_exact_access_scope(
            select(DocumentEntity, Document)
            .join(Document, DocumentEntity.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(DocumentEntity.entity_value.ilike(pattern))
            .limit(limit * 3),
            access_scope,
        )
    ).all()
    for entity, document in entity_rows:
        if _contains_exact_phrase(entity.entity_value, phrase):
            candidates.append(("entity", document, entity.page_number))

    document_rows = db.execute(
        _apply_exact_access_scope(
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(
                or_(
                    Document.original_filename.ilike(pattern),
                    Document.source_path.ilike(pattern),
                )
            )
            .limit(limit * 3),
            access_scope,
        )
    ).scalars().all()
    for document in document_rows:
        if _contains_exact_phrase(document.original_filename, phrase) or _contains_exact_phrase(
            document.source_path, phrase
        ):
            candidates.append(("filename", document, None))

    for matched_in, model, column_name in (
        ("page_text", DocumentPage, "text"),
        ("block_text", DocumentBlock, "text"),
        ("chunk_text", DocumentChunk, "chunk_text"),
    ):
        text_column = getattr(model, column_name)
        rows = db.execute(
            _apply_exact_access_scope(
                select(model, Document)
                .join(Document, model.document_id == Document.id)
                .where(Document.deleted_at.is_(None))
                .where(text_column.ilike(pattern))
                .limit(limit * 3),
                access_scope,
            )
        ).all()
        for value, document in rows:
            if _contains_exact_phrase(getattr(value, column_name), phrase):
                candidates.append((matched_in, document, getattr(value, "page_number", None)))

    results: list[ExactMatch] = []
    seen_doc_ids: set[int] = set()
    priority = {"entity": 0, "filename": 1, "page_text": 2, "block_text": 3, "chunk_text": 4}
    for matched_in, document, page_number in sorted(candidates, key=lambda item: priority[item[0]]):
        if document.id in seen_doc_ids:
            continue
        seen_doc_ids.add(document.id)
        results.append(
            ExactMatch(
                document_id=document.id,
                original_filename=document.original_filename,
                document_type=document.document_type or "",
                source_path=_visible_source_path(document, access_scope),
                matched_in=matched_in,
                matched_value=phrase,
                page_number=page_number,
            )
        )
    return results[:limit]


def _search_entities(
    db: Session,
    *,
    normalized: str,
    kind: str,
    limit: int,
    access_scope,
) -> list[ExactMatch]:
    """Search DocumentEntity for exact number matches."""
    # Map identifier kind to entity types
    entity_type_map = {
        "budget": ["budget_number"],
        "order": ["order_number"],
        "invoice": ["invoice_number"],
        "delivery_note": ["delivery_note_number"],
        "tax_id": ["tax_id", "cif", "nif"],
        "reference": ["reference", "document_number"],
        "document_number": ["budget_number", "order_number", "invoice_number", "document_number"],
        "generic": ["budget_number", "order_number", "invoice_number", "document_number", "reference"],
    }
    entity_types = entity_type_map.get(kind, ["budget_number", "order_number", "invoice_number"])

    # Also search for the normalized number as a substring
    pattern = _make_boundary_pattern(normalized)

    stmt = (
        select(DocumentEntity, Document)
        .join(Document, DocumentEntity.document_id == Document.id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentEntity.entity_type.in_(entity_types))
        .where(DocumentEntity.entity_value.ilike(pattern))
        .limit(limit)
    )
    rows = db.execute(_apply_exact_access_scope(stmt, access_scope)).all()
    results = []
    for entity, doc in rows:
        if not _contains_exact_number(entity.entity_value, normalized):
            continue
        results.append(
            ExactMatch(
                document_id=doc.id,
                original_filename=doc.original_filename,
                document_type=doc.document_type or "",
                source_path=_visible_source_path(doc, access_scope),
                matched_in="entity",
                matched_value=entity.entity_value or "",
            )
        )
    return results


def _search_page_text(
    db: Session,
    *,
    normalized: str,
    limit: int,
    access_scope,
) -> list[ExactMatch]:
    """Search DocumentPage.text for exact number matches with word boundaries."""
    pattern = f"%{normalized}%"
    stmt = (
        select(DocumentPage, Document)
        .join(Document, DocumentPage.document_id == Document.id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentPage.text.ilike(pattern))
        .limit(limit * 3)
    )
    rows = db.execute(_apply_exact_access_scope(stmt, access_scope)).all()
    results = []
    seen: set[int] = set()
    for page, doc in rows:
        if doc.id in seen:
            continue
        # Verify word boundary match in Python (SQLite ILIKE doesn't support \b)
        # Check the candidate after the SQL pre-filter so a longer number
        # (for example 12503980) never satisfies 250398.
        if _contains_exact_number(page.text, normalized):
            seen.add(doc.id)
            results.append(
                ExactMatch(
                    document_id=doc.id,
                    original_filename=doc.original_filename,
                    document_type=doc.document_type or "",
                    source_path=_visible_source_path(doc, access_scope),
                    matched_in="page_text",
                    matched_value=normalized,
                    page_number=page.page_number,
                )
            )
    return results[:limit]


def _search_block_text(
    db: Session,
    *,
    normalized: str,
    limit: int,
    access_scope,
) -> list[ExactMatch]:
    """Search DocumentBlock.text for exact number matches."""
    pattern = f"%{normalized}%"
    stmt = (
        select(DocumentBlock, Document)
        .join(Document, DocumentBlock.document_id == Document.id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentBlock.text.ilike(pattern))
        .limit(limit * 3)
    )
    rows = db.execute(_apply_exact_access_scope(stmt, access_scope)).all()
    results = []
    seen: set[int] = set()
    for block, doc in rows:
        if doc.id in seen:
            continue
        if _contains_exact_number(block.text, normalized):
            seen.add(doc.id)
            results.append(
                ExactMatch(
                    document_id=doc.id,
                    original_filename=doc.original_filename,
                    document_type=doc.document_type or "",
                    source_path=_visible_source_path(doc, access_scope),
                    matched_in="block_text",
                    matched_value=normalized,
                    page_number=block.page_number,
                )
            )
    return results[:limit]


def _search_chunk_text(
    db: Session,
    *,
    normalized: str,
    limit: int,
    access_scope,
) -> list[ExactMatch]:
    """Search DocumentChunk.chunk_text for exact number matches."""
    pattern = f"%{normalized}%"
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.deleted_at.is_(None))
        .where(DocumentChunk.chunk_text.ilike(pattern))
        .limit(limit * 3)
    )
    rows = db.execute(_apply_exact_access_scope(stmt, access_scope)).all()
    results = []
    seen: set[int] = set()
    for chunk, doc in rows:
        if doc.id in seen:
            continue
        if _contains_exact_number(chunk.chunk_text, normalized):
            seen.add(doc.id)
            results.append(
                ExactMatch(
                    document_id=doc.id,
                    original_filename=doc.original_filename,
                    document_type=doc.document_type or "",
                    source_path=_visible_source_path(doc, access_scope),
                    matched_in="chunk_text",
                    matched_value=normalized,
                    page_number=chunk.page_number,
                )
            )
    return results[:limit]


def _search_filename(
    db: Session,
    *,
    normalized: str,
    number: str,
    limit: int,
    access_scope,
) -> list[ExactMatch]:
    """Search Document.original_filename and source_path for the number."""
    # Also try the original (non-normalized) number
    pattern_norm = f"%{normalized}%"
    pattern_orig = f"%{number}%"
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(
            or_(
                Document.original_filename.ilike(pattern_norm),
                Document.original_filename.ilike(pattern_orig),
                Document.source_path.ilike(pattern_norm),
                Document.source_path.ilike(pattern_orig),
            )
        )
        .limit(limit)
    )
    docs = db.execute(_apply_exact_access_scope(stmt, access_scope)).scalars().all()
    results = []
    for doc in docs:
        if not (
            _contains_exact_number(doc.original_filename, normalized)
            or _contains_exact_number(doc.source_path, normalized)
        ):
            continue
        results.append(
            ExactMatch(
                document_id=doc.id,
                original_filename=doc.original_filename,
                document_type=doc.document_type or "",
                source_path=_visible_source_path(doc, access_scope),
                matched_in="filename",
                matched_value=number,
            )
        )
    return results


def _apply_exact_access_scope(stmt, access_scope):
    """Restrict an exact-search statement before it reads document content."""
    from app.services.tenant_access import apply_access_predicates

    return apply_access_predicates(stmt, access_scope, document_column=Document.id)


def _visible_source_path(document: Document, access_scope) -> str | None:
    """Keep physical paths out of non-administrator exact-search results."""
    return document.source_path if access_scope.is_admin else None


def select_best_exact_match(
    matches: list[ExactMatch],
    *,
    question_kind: str | None = None,
) -> ExactMatch | None:
    """Select the best exact match from a list.

    Priority:
    1. Entity match (highest confidence - structured data)
    2. Filename match (explicit in filename)
    3. Page/block text match (found in document content)
    4. Chunk text match (found in embedding chunk)

    If there are multiple matches of the same priority, prefer the
    one whose document_type best matches the question kind.
    """
    if not matches:
        return None

    priority_order = {"entity": 0, "filename": 1, "page_text": 2, "block_text": 3, "chunk_text": 4}
    type_preference = {
        "budget": ["presupuesto"],
        "order": ["pedido"],
        "invoice": ["factura"],
        "delivery_note": ["albaran"],
    }

    def sort_key(m: ExactMatch) -> tuple[int, int]:
        p = priority_order.get(m.matched_in, 5)
        # Prefer matching document type
        preferred_types = type_preference.get(question_kind or "", [])
        t = 0 if m.document_type in preferred_types else 1
        return (p, t)

    sorted_matches = sorted(matches, key=sort_key)
    return sorted_matches[0]
