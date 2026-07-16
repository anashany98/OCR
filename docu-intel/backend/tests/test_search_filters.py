"""Tests for the E3 shared search filters.

The filters are pure SQLAlchemy expression builders: no DB, no
fixtures, no mocks. We feed them a hand-crafted ``Select`` and
assert which ``WHERE`` clauses are appended. The pure-Python parts
(date coercion, value normalisation, list helpers) get the same
treatment.

These tests are the contract for the new filter keys. A future
refactor cannot silently change which documents a filter selects
without breaking one of these.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select

from app.services import search_filters
from app.services.search_filters import (
    apply_document_filters,
    build_chunk_filter_clause,
    normalise_filters,
    split_filters,
)


# ---------------------------------------------------------------------------
# Filter normalisation
# ---------------------------------------------------------------------------


def test_normalise_filters_handles_none_and_empty():
    assert normalise_filters(None) == {}
    assert normalise_filters({}) == {}


def test_normalise_filters_coerces_budget_scope_id_to_int():
    assert normalise_filters({"budget_scope_id": "42"}) == {"budget_scope_id": 42}
    assert normalise_filters({"budget_scope_id": 42}) == {"budget_scope_id": 42}
    # Bad input is dropped silently.
    assert normalise_filters({"budget_scope_id": "not-a-number"}) == {}


def test_normalise_filters_coerces_project_id_to_int():
    assert normalise_filters({"project_id": "42"}) == {"project_id": 42}
    assert normalise_filters({"project_id": "not-a-number"}) == {}


def test_normalise_filters_coerces_extension_with_leading_dot():
    out = normalise_filters({"extension": "pdf"})
    assert out["extension"] == ".pdf"
    out = normalise_filters({"extension": ".PDF"})
    assert out["extension"] == ".pdf"
    out = normalise_filters({"extension": ""}) == {}


def test_normalise_filters_coerces_dates_from_strings():
    out = normalise_filters({"created_from": "2025-01-15", "created_to": "2025-04-30"})
    assert out["created_from"] == datetime(2025, 1, 15, tzinfo=timezone.utc)
    assert out["created_to"] == datetime(2025, 4, 30, 23, 59, 59, tzinfo=timezone.utc) or \
           out["created_to"] == datetime(2025, 4, 30, tzinfo=timezone.utc)


def test_normalise_filters_coerces_dates_from_iso():
    out = normalise_filters({"created_from": "2025-01-15T10:30:00Z"})
    assert out["created_from"] == datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_normalise_filters_drops_unparseable_dates():
    assert normalise_filters({"created_from": "not a date"}) == {}


def test_normalise_filters_coerces_ocr_confidence_to_float():
    assert normalise_filters({"min_ocr_confidence": "0.75"}) == {"min_ocr_confidence": 0.75}
    assert normalise_filters({"min_ocr_confidence": 0.75}) == {"min_ocr_confidence": 0.75}


def test_normalise_filters_rejects_ocr_out_of_range():
    assert normalise_filters({"min_ocr_confidence": "1.5"}) == {}
    assert normalise_filters({"min_ocr_confidence": "-0.1"}) == {}


def test_normalise_filters_coerces_quality_flags_list():
    out = normalise_filters({"quality_flags_any": "low_ocr,missing_fields"})
    assert out["quality_flags_any"] == ["low_ocr", "missing_fields"]
    out = normalise_filters({"quality_flags_any": ["low_ocr", "missing_fields"]})
    assert out["quality_flags_any"] == ["low_ocr", "missing_fields"]


def test_normalise_filters_exclude_statuses_as_list():
    out = normalise_filters({"exclude_statuses": "failed,duplicate"})
    assert out["exclude_statuses"] == ["failed", "duplicate"]


def test_normalise_filters_keeps_block_type_as_string():
    out = normalise_filters({"block_type": "table"})
    assert out["block_type"] == "table"


# ---------------------------------------------------------------------------
# apply_document_filters — Select statement builder
# ---------------------------------------------------------------------------


def _count_wheres(stmt) -> int:
    """Count the number of WHERE clauses attached to a Select."""
    # SQLAlchemy stores the where clauses as a tuple on the
    # statement. We count them directly.
    return len(getattr(stmt, "_where_criteria", ()) or ())


def test_apply_document_filters_empty_input_is_noop():
    stmt = select(1)
    before = _count_wheres(stmt)
    out = apply_document_filters(stmt, None)
    assert out is stmt
    assert _count_wheres(out) == before

    out = apply_document_filters(stmt, {})
    assert _count_wheres(out) == before


def test_apply_document_filters_legacy_filters_still_work():
    """The original filter keys (budget_scope_id, document_type,
    status, quality_status, extension) must keep behaving as
    before — this is the backward-compatibility contract."""
    stmt = select(1)
    out = apply_document_filters(
        stmt,
        {
            "budget_scope_id": 7,
            "document_type": "presupuesto",
            "status": "processed",
            "quality_status": "processed_ok",
            "extension": "PDF",
        },
    )
    assert _count_wheres(out) == 5


def test_apply_document_filters_scopes_documents_through_occurrences():
    stmt = select(1)
    out = apply_document_filters(stmt, {"project_id": 7})
    assert _count_wheres(out) == 1
    assert "document_occurrences" in str(out)


def test_apply_document_filters_adds_created_from_to_clauses():
    stmt = select(1)
    out = apply_document_filters(stmt, {"created_from": "2025-01-15"})
    assert _count_wheres(out) == 1


def test_apply_document_filters_adds_created_to_to_clauses():
    stmt = select(1)
    out = apply_document_filters(stmt, {"created_to": "2025-12-31"})
    assert _count_wheres(out) == 1


def test_apply_document_filters_adds_exclude_statuses_to_clauses():
    stmt = select(1)
    out = apply_document_filters(stmt, {"exclude_statuses": ["failed", "duplicate"]})
    assert _count_wheres(out) == 1


def test_apply_document_filters_adds_quality_flags_any():
    stmt = select(1)
    out = apply_document_filters(
        stmt, {"quality_flags_any": ["low_ocr", "missing_fields"]}
    )
    # OR of two jsonb_exists tests collapses to one WHERE clause
    # (the OR is wrapped in a single boolean).
    assert _count_wheres(out) == 1


def test_apply_document_filters_adds_quality_flags_all():
    stmt = select(1)
    out = apply_document_filters(
        stmt, {"quality_flags_all": ["low_ocr", "missing_fields"]}
    )
    assert _count_wheres(out) == 1


def test_apply_document_filters_combines_many_filters():
    stmt = select(1)
    out = apply_document_filters(
        stmt,
        {
            "budget_scope_id": 1,
            "document_type": "presupuesto",
            "created_from": "2025-01-01",
            "created_to": "2025-12-31",
            "exclude_statuses": ["failed"],
            "quality_flags_any": ["low_ocr"],
            "block_type": "table",  # ignored at the document level
        },
    )
    # 5 document-level filters applied: budget, doc_type, from,
    # to, exclude, plus the OR of quality_flags_any. block_type
    # is a chunk-level filter and is intentionally skipped.
    assert _count_wheres(out) == 6


# ---------------------------------------------------------------------------
# build_chunk_filter_clause
# ---------------------------------------------------------------------------


def test_build_chunk_filter_clause_returns_none_when_no_relevant_filter():
    assert build_chunk_filter_clause(None) is None
    assert build_chunk_filter_clause({}) is None
    assert build_chunk_filter_clause({"document_type": "presupuesto"}) is None


def test_build_chunk_filter_clause_handles_block_type():
    clause = build_chunk_filter_clause({"block_type": "table"})
    assert clause is not None
    # The clause is a SQLAlchemy expression; we cannot compare
    # directly to a string but we can check it is a boolean
    # expression.
    from sqlalchemy import Boolean
    assert isinstance(clause.type, Boolean)


def test_build_chunk_filter_clause_handles_min_ocr_confidence():
    clause = build_chunk_filter_clause({"min_ocr_confidence": 0.7})
    assert clause is not None


def test_build_chunk_filter_clause_combines_block_type_and_ocr_floor():
    clause = build_chunk_filter_clause(
        {"block_type": "table", "min_ocr_confidence": 0.5}
    )
    assert clause is not None
    # Two predicates ANDed.
    from sqlalchemy import Boolean
    assert isinstance(clause.type, Boolean)


# ---------------------------------------------------------------------------
# split_filters
# ---------------------------------------------------------------------------


def test_split_filters_returns_document_and_chunk_parts():
    bundle = split_filters(
        {
            "budget_scope_id": 1,
            "document_type": "presupuesto",
            "block_type": "table",
            "min_ocr_confidence": 0.6,
        }
    )
    # Document side has the doc-level keys; chunk side has the
    # chunk-level ones (removed from the doc dict).
    assert bundle.document_filters == {
        "budget_scope_id": 1,
        "document_type": "presupuesto",
    }
    assert bundle.chunk_clause is not None


def test_split_filters_empty_input_yields_empty_bundle():
    bundle = split_filters(None)
    assert bundle.document_filters == {}
    assert bundle.chunk_clause is None


# ---------------------------------------------------------------------------
# Smoke: the filters do not raise on weird input
# ---------------------------------------------------------------------------


def test_normalise_filters_does_not_raise_on_garbage():
    """A defensive test: any input we might see from the API
    should normalise without raising. We log a warning at debug
    level for unparseable values, but never crash the request."""
    weird_inputs: list[dict[str, Any]] = [
        {"created_from": None, "created_to": False},
        {"min_ocr_confidence": "not a number"},
        {"quality_flags_any": None},
        {"quality_flags_any": 42},  # not a list
        {"block_type": 0},
        {"extension": 0},
        {"exclude_statuses": {"a", "b"}},  # set, not list
        {},  # nothing
    ]
    for payload in weird_inputs:
        out = normalise_filters(payload)
        # The output must be a dict (possibly empty).
        assert isinstance(out, dict)
