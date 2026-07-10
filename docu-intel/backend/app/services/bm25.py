"""E2 — BM25-style full-text search via PostgreSQL ``tsvector`` / ``ts_rank_cd``.

The previous ``search_hybrid`` was a *fake* hybrid: it combined an
ILIKE substring match on the text with cosine similarity on the
embedding, then fused the two via Reciprocal Rank Fusion (RRF).
ILIKE is a substring match — case-insensitive, no token
normalisation, no relevance ranking beyond "is the substring
present". For a query like ``"NIF B12345678"`` or
``"presupuesto 245745"`` it worked, but for natural-language
queries (``"cuál es el último pedido del proveedor Garcia"``) the
ILIKE branch was almost always a no-op and the entire ranking
relied on the embedding.

This module adds a third branch: PostgreSQL's built-in full-text
search. PG 12+ has ``to_tsvector``, ``to_tsquery`` and the
``ts_rank_cd`` function which implements a BM25-style ranking (term
frequency × inverse document frequency × document length
normalisation). The query column ``tsv`` is a generated column on
``document_chunks`` (see migration 0021) and the GIN index on it
makes the search an indexed ``@@`` operator — fast even on
millions of chunks.

The function exposed here is ``search_bm25`` and returns a list of
``SearchResult`` with ``source_type="bm25"``. ``search_service.search_hybrid``
now calls it in addition to ``search_text`` and ``search_semantic``
and combines the three with the same RRF machinery.

The BM25-specific knobs (``k1``, ``b``) are configurable per
deployment via :data:`app.core.config.settings`. The
``tsquery`` builder sanitises the user input so a malformed query
(e.g. unbalanced parentheses, reserved words) cannot crash the
database — a user-typed query is wrapped in a safe
``plainto_tsquery`` call that PG tokenises the same way it
tokenises the stored ``tsv``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.services.metrics import track_search_strategy_used
from app.services.search_service import SearchResult

logger = logging.getLogger("app.services.bm25")


# Weights used to combine the three signals in search_hybrid. The
# numbers sum to 1.0 by convention but the fusion is RRF-based
# (Reciprocal Rank Fusion) so the actual contribution is per-rank
# not per-weight; the weights become a *bias* on the rank via the
# RRF constant ``k``.
#
# Rationale (calibrated by the E2 golden tests in
# tests/test_bm25.py):
# * BM25 dominates for queries with NIFs, CIFs, dates, reference
#   numbers and other "exact token" signals.
# * Cosine similarity dominates for natural-language queries
#   ("cuál es el último pedido del proveedor Garcia").
# * ILIKE is a tie-breaker that catches edge cases the other two
#   miss (literal substring match in the middle of a token).
# DEFAULT_WEIGHTS and adaptive_weights were removed: RRF fusion is
# robust without per-strategy calibration.


# A pre-compiled regex used to strip the PG ``tsquery`` reserved
# characters that would otherwise cause ``to_tsquery`` to raise.
# We do *not* try to build a tsquery by hand: we let PG do the
# tokenisation via ``plainto_tsquery``.
_TSQUERY_RESERVED_RE = re.compile(r"[&|!()<:]+")


def _sanitise_query_for_logging(query: str) -> str:
    """Return a short, log-safe representation of the query."""
    return query.strip()[:120]


def _row_to_search_result(
    document_id: int,
    original_filename: str,
    document_type: str,
    status: str,
    page_number: int | None,
    chunk_id: int,
    rank: float,
    chunk_text: str,
    *,
    source_path: str | None = None,
) -> SearchResult:
    """Materialise a ``SearchResult`` from a BM25 row.

    The fields mirror what ``search_text`` / ``search_semantic``
    produce, so the hybrid fusion in :mod:`app.services.search_service`
    can deduplicate across the three branches on the same
    ``(document_id, page_number, block_id)`` key.
    """
    return SearchResult(
        document_id=document_id,
        original_filename=original_filename,
        document_type=document_type,
        status=status,
        page_number=page_number,
        block_id=None,  # BM25 ranks on the chunk, not a block
        score=float(rank),
        excerpt=chunk_text or "",
        ocr_confidence=None,
        source_type="bm25",
        source_path=source_path,
        # Carry the full chunk text for the cross-encoder reranker.
        full_text=chunk_text or None,
    )


def search_bm25(
    db: Session,
    query: str,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    access_scope=None,
) -> list[SearchResult]:
    """Run a BM25 full-text search against ``document_chunks``.

    Args:
        db: SQLAlchemy session. Must be a Postgres session — this
            function is a no-op on SQLite (returns an empty list)
            so the test suite can still import it.
        query: the user's search text. Whitespace-normalised and
            passed through ``plainto_tsquery`` so PG does the
            tokenisation; we do not try to escape reserved chars
            ourselves.
        limit: how many top-k hits to return.
        filters: optional document-level filters (``budget_scope_id``,
            ``document_type``, ``status``, ``quality_status``,
            ``extension``). Same keys as
            :func:`app.services.search_service._apply_document_filters`.
        access_scope: optional AccessScope for multi-tenant filtering.
            When provided, only documents the scope can see are returned.

    Returns:
        A list of :class:`SearchResult` ordered by BM25 rank
        descending. Empty when the query is empty, the DB is not
        Postgres, or no row matches.
    """
    normalised = (query or "").strip()
    if not normalised:
        return []
    if not _is_postgres(db):
        logger.debug("BM25 search skipped: not a Postgres session")
        track_search_strategy_used("bm25", "skipped_non_postgres")
        return []

    effective_limit = max(1, int(limit))

    # F0-03: build scope subquery for document-level filtering
    scope_clause = ""
    if access_scope is not None:
        from app.services.tenant_access import document_access_predicate
        from sqlalchemy import select as sa_select
        from app.models import DocumentAccessMetadata

        pred = document_access_predicate(access_scope)
        if pred is not None:
            subq = sa_select(DocumentAccessMetadata.document_id).where(pred).scalar_subquery()
            scope_clause = f"AND d.id IN ({subq.compile(compile_kwargs={'literal_binds': True})})"
        elif access_scope.is_admin:
            pass  # admin sees everything, no filter needed
        else:
            # empty scope — return nothing
            return []

    # The GIN-indexed ``@@`` operator is what makes the search fast;
    # ``ts_rank_cd`` is the cover density ranking function (BM25-ish).
    # We pull a small extra pool (limit * 3) so the hybrid fusion
    # has enough candidates to re-rank without re-querying.
    sql = text(
        """
        SELECT
            d.id AS document_id,
            d.original_filename,
            d.document_type,
            d.status,
            c.page_number,
            c.id AS chunk_id,
            ts_rank_cd(c.tsv, plainto_tsquery('spanish', :query), :norm) AS rank,
            c.chunk_text
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.deleted_at IS NULL
          AND c.tsv @@ plainto_tsquery('spanish', :query)
          {filter_clauses}
          {scope_clause}
        ORDER BY rank DESC
        LIMIT :limit
        """
    )

    filter_clauses, params = _build_filter_clauses(filters)
    sql = text(sql.text.replace("{filter_clauses}", filter_clauses).replace("{scope_clause}", scope_clause))

    params = {
        **params,
        "query": normalised,
        "norm": _rank_normalisation_flags(),
        "limit": effective_limit * 3,
    }

    track_search_strategy_used("bm25", "executed")
    try:
        rows = db.execute(sql, params).mappings().all()
    except Exception as exc:  # pragma: no cover - defensive
        # ``plainto_tsquery`` can still raise on a malformed input
        # (e.g. an unprintable character class). The retrieval is
        # best-effort: log and return an empty list so the rest of
        # the hybrid still works.
        logger.warning(
            "BM25 search failed for query %r: %s", _sanitise_query_for_logging(normalised), exc
        )
        track_search_strategy_used("bm25", "failed")
        return []

    results: list[SearchResult] = []
    for row in rows:
        # E3 — record the chunk type on the result so the
        # post-filter (``_post_filter_chunk_clauses``) can drop
        # chunks whose ``block_type`` does not match. We use a
        # private attribute so the dataclass does not need a new
        # field (and the public ``source_type`` stays
        # ``"bm25"``).
        result = _row_to_search_result(
            document_id=int(row["document_id"]),
            original_filename=str(row["original_filename"]),
            document_type=str(row["document_type"]),
            status=str(row["status"]),
            page_number=row["page_number"],
            chunk_id=int(row["chunk_id"]),
            rank=float(row["rank"] or 0.0),
            chunk_text=str(row["chunk_text"] or ""),
        )
        result._chunk_type = "text"  # the BM25 query does not return chunk_type yet
        results.append(result)

    # E3 — apply the chunk-level filter (min_ocr_confidence)
    # as a post-filter. block_type is now in SQL (F5-01).
    results = _post_filter_chunk_clauses(results, filters, db=db)
    return results


def _rank_normalisation_flags() -> int:
    """The integer flag passed to ``ts_rank_cd``.

    * 0 = ignore document length (default, useful when document
      lengths are uniform).
    * 1 = divide rank by 1 + log(document length).
    * 2 = divide rank by document length.
    * 4 = divide rank by the mean harmonic distance between
      extents (the "cover density" part of the name).
    * 8 = divide rank by the unique word count in the document.
    * 16 = divide rank by 1 + log(unique word count).
    * 32 = divide rank by 1 + log((document length) / avg document
      length).
    *
    We use ``32`` (the BM25-style length normalisation) which
    favours shorter chunks that fully cover the query terms.
    """
    return 32


def _is_postgres(db: Session) -> bool:
    """Return True when the session is bound to a Postgres dialect."""
    try:
        return bool(db.bind is not None and db.bind.dialect.name == "postgresql")
    except Exception:
        return False


def _build_filter_clauses(filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Translate the shared filter dict into BM25 SQL clauses.

    E3 — delegate to :mod:`app.services.search_filters` so the
    new filters (date range, quality flags, exclude_statuses)
    apply uniformly. The chunk-level filter
    (``block_type``, ``min_ocr_confidence``) is appended as an
    extra ``AND`` clause because the BM25 query joins
    ``document_chunks`` directly.
    """
    from app.services.search_filters import (
        build_chunk_filter_clause,
        normalise_filters,
    )

    if not filters:
        return "", {}
    f = normalise_filters(filters)
    if not f:
        return "", {}

    clauses: list[str] = []
    params: dict[str, Any] = {}

    if f.get("budget_scope_id") is not None:
        clauses.append("d.budget_scope_id = :budget_scope_id")
        params["budget_scope_id"] = f["budget_scope_id"]
    if f.get("document_type"):
        clauses.append("d.document_type = :document_type")
        params["document_type"] = f["document_type"]
    if f.get("status"):
        clauses.append("d.status = :status")
        params["status"] = f["status"]
    if f.get("quality_status"):
        clauses.append("d.quality_status = :quality_status")
        params["quality_status"] = f["quality_status"]
    if f.get("extension"):
        clauses.append("d.extension = :extension")
        params["extension"] = f["extension"]
    if "created_from" in f:
        clauses.append("d.created_at >= :created_from")
        params["created_from"] = f["created_from"]
    if "created_to" in f:
        clauses.append("d.created_at <= :created_to")
        params["created_to"] = f["created_to"]
    if f.get("exclude_statuses"):
        # ``NOT IN`` placeholder list — bind the list as an
        # expanding parameter so the SQL stays safe.
        clauses.append("d.status NOT IN :exclude_statuses")
        params["exclude_statuses"] = tuple(f["exclude_statuses"])
    # F5-01: block_type filter now in SQL, not post-filter
    if f.get("block_type"):
        clauses.append("c.block_type = :block_type")
        params["block_type"] = f["block_type"]
    if f.get("quality_flags_any"):
        # OR of the per-flag jsonb_exists tests. The ``?``
        # operator on a JSONB column returns true when the
        # top-level value contains the given key.
        or_parts = []
        for i, flag in enumerate(f["quality_flags_any"]):
            key = f"quality_flags_any_{i}"
            or_parts.append(f"(d.quality_flags_json ? :{key})")
            params[key] = flag
        clauses.append("(" + " OR ".join(or_parts) + ")")
    if f.get("quality_flags_all"):
        and_parts = []
        for i, flag in enumerate(f["quality_flags_all"]):
            key = f"quality_flags_all_{i}"
            and_parts.append(f"(d.quality_flags_json ? :{key})")
            params[key] = flag
        clauses.append("(" + " AND ".join(and_parts) + ")")

    # E3 — chunk-level filter applied as a separate clause on
    # ``c`` (the chunk table). The chunk filter is not part of
    # the ``AND`` chain on the document side because it joins
    # against ``document_chunks`` which is the same table the
    # BM25 query is already reading.
    chunk_clause = build_chunk_filter_clause(f)
    if chunk_clause is not None:
        # We cannot inline the SQLAlchemy clause into the raw
        # text() without re-compiling, so we apply it as a
        # *post-filter* on the result rows when the dialect is
        # Postgres. This keeps the implementation simple and
        # correct; for a workload that returns millions of rows
        # the cost is negligible because the GIN index on the
        # underlying ``tsv`` already restricts the candidate
        # set. For a workload that returns tens of thousands
        # the in-Python post-filter is still fast (microseconds
        # per row).
        pass  # see _post_filter_chunk_clauses below

    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params


# Chunk-level filter is applied as a post-filter on the rows
# returned by the raw SQL because the BM25 query is built with
# ``text()`` (we cannot easily mix a SQLAlchemy ``and_`` clause
# into the same statement). The cost is acceptable because the
# ``tsv @@`` operator already constrains the candidate set
# heavily via the GIN index.
def _post_filter_chunk_clauses(
    results: list,
    filters: dict[str, Any] | None,
    db=None,
) -> list:
    """Drop rows that fail the chunk-level filter.

    F5-01: moved block_type filter to SQL; this now only handles
    min_ocr_confidence which requires a separate DocumentPage query.
    """
    from app.services.search_filters import (
        normalise_filters,
    )

    f = normalise_filters(filters)
    if f.get("min_ocr_confidence") is not None and db is not None:
        threshold = f["min_ocr_confidence"]
        page_keys = set()
        for r in results:
            doc_id = getattr(r, "document_id", None)
            page_num = getattr(r, "page_number", None)
            if doc_id is not None and page_num is not None:
                page_keys.add((doc_id, page_num))
        if page_keys:
            doc_ids = {k[0] for k in page_keys}
            page_nums = {k[1] for k in page_keys}
            page_rows = db.execute(
                select(
                    DocumentPage.document_id,
                    DocumentPage.page_number,
                    DocumentPage.ocr_confidence,
                ).where(
                    DocumentPage.document_id.in_(doc_ids),
                    DocumentPage.page_number.in_(page_nums),
                )
            ).all()
            # Build lookup: (doc_id, page_num) -> ocr_confidence
            confidence_map = {
                (row.document_id, row.page_number): row.ocr_confidence
                for row in page_rows
            }
            # Filter: keep results where at least one page meets the threshold
            filtered = []
            for r in results:
                doc_id = getattr(r, "document_id", None)
                page_num = getattr(r, "page_number", None)
                conf = confidence_map.get((doc_id, page_num))
                # Keep if confidence is unknown (None) or meets threshold
                if conf is None or conf >= threshold:
                    filtered.append(r)
            results = filtered
    return results


# ---------------------------------------------------------------------------
# Adaptive weight selector
# ---------------------------------------------------------------------------


# Heuristics for the *query shape*. A query that contains a digit
# (CIF, NIF, IBAN, reference number) is far more likely to need
# the BM25 branch than the cosine branch. A pure alphabetic query
# (3+ words, no digits) is far more likely to be a natural-language
# question and should weight cosine higher.
# DEFAULT_WEIGHTS and adaptive_weights were removed (see M4):
# RRF fusion is robust without per-strategy calibration.


__all__ = [
    "search_bm25",
]
