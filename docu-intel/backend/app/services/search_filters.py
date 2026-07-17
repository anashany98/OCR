"""E3 — Shared search filters for the three retrieval strategies.

The retriever used to apply only a handful of coarse filters
(``budget_scope_id``, ``document_type``, ``status``, ``extension``)
in :func:`app.services.search_service._apply_document_filters`.
Adding the new ones (date range, block type, OCR confidence,
quality flags) inline would have meant duplicating the SQL
fragments in every retrieval branch (ILIKE text, BM25, cosine),
which is exactly the kind of drift that the cascade was supposed
to prevent. This module centralises the filter logic so all three
branches apply the same set of constraints on the same set of
documents.

Filters supported:

* ``created_from`` / ``created_to`` — ISO date strings, applied to
  ``documents.created_at``. Inclusive on both ends.
* ``block_type`` — ``"text" | "table" | "heading"``, applied to
  ``document_chunks.chunk_type`` (E1). This is a *chunk-level*
  filter so the SQL is shaped slightly differently from the
  document-level filters; the helper is documented to return an
  optional clause that the caller appends to its chunk-level
  ``FROM ... JOIN`` chain.
* ``min_ocr_confidence`` — float in ``[0, 1]``. Filters pages
  whose ``document_pages.ocr_confidence`` is below the floor.
  Implementation: documents whose **any** page passes the floor
  are returned (we keep low-confidence pages in the result
  rather than dropping the whole document).
* ``quality_flags_any`` — list of flag strings; the document must
  have at least one of them in ``documents.quality_flags_json``.
* ``quality_flags_all`` — list of flag strings; the document must
  have **all** of them.
* ``exclude_statuses`` — list of status strings; documents whose
  status is in the list are excluded. The complementary filter
  to the existing ``status`` (which is inclusive).

The existing filters (``budget_scope_id``, ``document_type``,
``status``, ``quality_status``, ``extension``) are still
supported; the helpers keep their public names for backward
compatibility.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.sql import Select

from app.core.config import settings
from app.models import Document, DocumentChunk, DocumentPage
from app.models.project import DocumentOccurrence
from app.services.ocr_page_roles import ocr_meets_threshold_clause

logger = logging.getLogger("app.services.search_filters")


# ---------------------------------------------------------------------------
# Filter normalisation
# ---------------------------------------------------------------------------


def _coerce_datetime(value: Any) -> datetime | None:
    """Coerce a string / date / datetime to a timezone-aware
    datetime. Returns ``None`` for unparseable inputs so the
    caller can decide whether to fail or ignore."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            cleaned = value.strip()
            if "T" in cleaned or " " in cleaned:
                parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            else:
                parsed = datetime.fromisoformat(cleaned)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            logger.debug("search_filters: cannot parse %r as datetime", value)
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= f <= 1.0):
        return None
    return f


def _coerce_str_list(value: Any) -> list[str]:
    """Coerce a list / set / comma-separated string to a list of
    non-empty trimmed strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, Iterable):
        return [str(s).strip() for s in value if s and str(s).strip()]
    return []


def normalise_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise every supported filter key into a canonical
    Python type. Unknown keys are dropped silently so a caller
    passing a typo doesn't crash the request; the new keys are
    logged at debug level for diagnostics."""
    if not filters:
        return {}
    out: dict[str, Any] = {}

    if "budget_scope_id" in filters:
        with contextlib.suppress(TypeError, ValueError):
            out["budget_scope_id"] = int(filters["budget_scope_id"])
    # A project is represented by document occurrences rather than by a
    # foreign key on ``documents``: a SHA-backed document can belong to more
    # than one project. Keep the filter at the occurrence layer so a chat
    # session never broadens its retrieval merely because it has project
    # context instead of a budget identifier.
    if "project_id" in filters:
        with contextlib.suppress(TypeError, ValueError):
            out["project_id"] = int(filters["project_id"])
    if filters.get("document_type"):
        out["document_type"] = str(filters["document_type"])
    if filters.get("status"):
        out["status"] = str(filters["status"])
    if filters.get("quality_status"):
        out["quality_status"] = str(filters["quality_status"])
    if filters.get("extension"):
        ext = str(filters["extension"]).lower()
        out["extension"] = ext if ext.startswith(".") else ("." + ext if ext else "")
    # CTX-4: scope guard filter — restricts the search to documents
    # whose ``source_path`` matches a substring (e.g. ``%Presupuesto
    # 260009%``). Useful for the in-conversation budget scope where
    # the user has not been registered in a ``budget_scope`` row yet
    # but the documents all live in a folder with the budget number.
    if filters.get("source_path_like"):
        like = str(filters["source_path_like"]).strip()
        if like:
            out["source_path_like"] = like

    created_from = _coerce_datetime(filters.get("created_from"))
    if created_from is not None:
        out["created_from"] = created_from
    created_to = _coerce_datetime(filters.get("created_to"))
    if created_to is not None:
        out["created_to"] = created_to

    min_ocr = _coerce_float(filters.get("min_ocr_confidence"))
    if min_ocr is not None:
        out["min_ocr_confidence"] = min_ocr

    block_type = filters.get("block_type")
    if block_type:
        out["block_type"] = str(block_type)

    flags_any = _coerce_str_list(filters.get("quality_flags_any"))
    if flags_any:
        out["quality_flags_any"] = flags_any
    flags_all = _coerce_str_list(filters.get("quality_flags_all"))
    if flags_all:
        out["quality_flags_all"] = flags_all

    exclude = _coerce_str_list(filters.get("exclude_statuses"))
    if exclude:
        out["exclude_statuses"] = exclude

    # Warn when a date range is suspiciously wide so an
    # operator-typo does not silently return the whole corpus.
    if "created_from" in out and "created_to" in out:
        delta = (out["created_to"] - out["created_from"]).days
        if delta > settings.search_filter_max_date_range_days:
            logger.warning(
                "search_filters: requested range of %d days exceeds the "
                "search_filter_max_date_range_days=%d; results will not "
                "be limited further",
                delta,
                settings.search_filter_max_date_range_days,
            )

    return out


# ---------------------------------------------------------------------------
# Document-level SQL filter builder
# ---------------------------------------------------------------------------


def apply_document_filters(
    stmt: Select,
    filters: dict[str, Any] | None,
) -> Select:
    """Apply the document-level subset of the filters to a
    ``SELECT`` statement.

    The chunk-level filters (``block_type``, ``min_ocr_confidence``)
    are intentionally **not** applied here: they require a
    different SQL shape (correlated subquery against
    ``document_chunks`` / ``document_pages``). Callers that hit
    the chunk table should call :func:`build_chunk_filter_clause`
    in addition to this helper.
    """
    f = normalise_filters(filters)
    if not f:
        return stmt

    if f.get("budget_scope_id"):
        stmt = stmt.where(Document.budget_scope_id == f["budget_scope_id"])
    if f.get("project_id"):
        stmt = stmt.where(
            select(DocumentOccurrence.id)
            .where(DocumentOccurrence.document_id == Document.id)
            .where(DocumentOccurrence.project_id == f["project_id"])
            .exists()
        )
    if f.get("document_type"):
        stmt = stmt.where(Document.document_type == f["document_type"])
    if f.get("status"):
        stmt = stmt.where(Document.status == f["status"])
    if f.get("quality_status"):
        stmt = stmt.where(Document.quality_status == f["quality_status"])
    if f.get("extension"):
        stmt = stmt.where(Document.extension == f["extension"])
    if f.get("source_path_like"):
        # SQL ``LIKE`` is case-sensitive on Postgres by default; we
        # use ILIKE so the scope guard works regardless of the casing
        # in the source path. The trigram index from migration 0031
        # accelerates this.
        stmt = stmt.where(Document.source_path.ilike(f["source_path_like"]))
    if "created_from" in f:
        stmt = stmt.where(Document.created_at >= f["created_from"])
    if "created_to" in f:
        stmt = stmt.where(Document.created_at <= f["created_to"])
    if f.get("exclude_statuses"):
        stmt = stmt.where(Document.status.notin_(f["exclude_statuses"]))
    if f.get("quality_flags_any"):
        # ``quality_flags_json`` is a JSONB array column. We use
        # ``jsonb_exists`` (a GIN-friendly wrapper around ``?``)
        # to test for each flag individually; the OR of the
        # tests keeps the doc when *any* flag matches. This is
        # portable across PG 12+ and avoids needing a separate
        # junction table.
        json_ors = [
            func.jsonb_exists(Document.quality_flags_json, flag) for flag in f["quality_flags_any"]
        ]
        stmt = stmt.where(or_(*json_ors))
    if f.get("quality_flags_all"):
        json_ands = [
            func.jsonb_exists(Document.quality_flags_json, flag) for flag in f["quality_flags_all"]
        ]
        stmt = stmt.where(and_(*json_ands))
    return stmt


# ---------------------------------------------------------------------------
# Chunk-level filter: block_type and min_ocr_confidence
# ---------------------------------------------------------------------------


def build_chunk_filter_clause(
    filters: dict[str, Any] | None,
) -> ColumnElement[bool] | None:
    """Return a SQL ``WHERE`` fragment that restricts a chunk-level
    query to the requested block type and OCR floor.

    The fragment is meant to be combined with the chunk-side
    filters of the BM25 / cosine / text branches. Returns
    ``None`` when neither filter is set so the caller does not
    have to add a no-op ``AND TRUE`` to its query.
    """
    f = normalise_filters(filters)
    clauses: list[ColumnElement[bool]] = []
    if f.get("block_type"):
        clauses.append(DocumentChunk.chunk_type == f["block_type"])
    if f.get("min_ocr_confidence") is not None:
        # "Any page on the document meets the OCR floor" -> the
        # document is good enough. We correlate via a subquery on
        # ``document_pages``. PG handles the rewrite into a
        # semi-join when the chunk query is against the same
        # document table; the cost is O(N) for the subquery but
        # the document_pages table is small per document.
        threshold = f["min_ocr_confidence"]
        good_page_subq = (
            select(DocumentPage.document_id)
            .where(
                DocumentPage.document_id == DocumentChunk.document_id,
                ocr_meets_threshold_clause(
                    DocumentPage.ocr_content_kind,
                    DocumentPage.ocr_confidence,
                    threshold,
                ),
            )
            .limit(1)
        )
        clauses.append(good_page_subq.exists())
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return and_(*clauses)


# ---------------------------------------------------------------------------
# Top-level entry point: returns the document-level filters applied
# to a Select *and* the chunk-level filter clause for chunk queries.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchFilterBundle:
    """The split of the user's filter dict between the document
    table and the chunk table.

    Attributes:
        document_filters: the normalised filter dict with the
            chunk-level keys removed. Suitable for
            :func:`apply_document_filters`.
        chunk_clause: a SQLAlchemy column expression to AND into
            the chunk-level ``WHERE`` (``None`` when no chunk
            filter applies).
    """

    document_filters: dict[str, Any]
    chunk_clause: ColumnElement[bool] | None


def split_filters(filters: dict[str, Any] | None) -> SearchFilterBundle:
    """Split a user filter dict into document-level and chunk-level
    parts. Convenience for callers that build a single SELECT
    joining documents + chunks and need both halves."""
    f = normalise_filters(filters)
    chunk_keys = {"block_type", "min_ocr_confidence"}
    document_filters = {k: v for k, v in f.items() if k not in chunk_keys}
    chunk_clause = build_chunk_filter_clause(f)
    return SearchFilterBundle(
        document_filters=document_filters,
        chunk_clause=chunk_clause,
    )


__all__ = [
    "normalise_filters",
    "apply_document_filters",
    "build_chunk_filter_clause",
    "split_filters",
    "SearchFilterBundle",
]
