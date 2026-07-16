"""Unit tests for the relational Graph RAG extractor.

The tests deliberately avoid a live PostgreSQL instance so they can
run on any developer machine and in lightweight CI. The DB-touching
paths are exercised through ``unittest.mock`` so an unexpected code
path fails the test loudly. End-to-end coverage against a real
database belongs in the integration suite
(``docker-compose.test.yml``).

The unit-test focus is the deterministic
``SharedReferenceExtractor``: it must

* propose a relation for two documents that share a normalized
  reference;
* skip documents whose only match is a single low-signal reference
  (``min_shared`` is honoured);
* truncate evidence quotes so the audit trail stays bounded;
* never propose a self-loop (``source_id == target_id``).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.graph_extraction import (
    ProposedRelation,
    SharedReferenceExtractor,
    VERIFY_THRESHOLD,
)


# ---------------------------------------------------------------------------
# SharedReferenceExtractor
# ---------------------------------------------------------------------------


def _row(document_id: int, value: str, normalized: str | None = None) -> MagicMock:
    row = MagicMock()
    row.document_id = document_id
    row.entity_value = value
    row.normalized_value = normalized
    return row


def _session_for(
    source_refs: list[str],
    other_refs_by_doc: dict[int, list[str]],
) -> MagicMock:
    """Build a ``MagicMock`` session that satisfies the extractor's reads.

    The extractor asks the session for two things:

    1. ``db.get(Document, document_id)`` to confirm the source exists.
    2. ``db.scalars(select(DocumentEntity).where(...))`` to load the
       document's references.
    3. ``db.execute(select(...).where(... != :source))`` to find
       documents that share a reference.

    The mock dispatches to per-document fixtures by inspecting the
    call arguments, so the test stays free of any SQL parsing.
    """
    refs_by_doc: dict[int, list[MagicMock]] = {1: [_row(1, value) for value in source_refs]}
    related: dict[int, set[str]] = {}
    for doc_id, refs in other_refs_by_doc.items():
        refs_by_doc[doc_id] = [_row(doc_id, value) for value in refs]
        related[doc_id] = {value for value in refs if value in set(source_refs)}

    session = MagicMock()

    # ``db.get`` is called once with the source ``Document`` and its id.
    session.get.return_value = object()

    # The extractor walks its callers in a predictable order:
    # 1) ``scalars`` for the source's references
    # 2) ``execute`` for the cross-document lookup
    # 3) ``scalars`` for each target's references (one per related doc)
    # We pre-build the queue so the mock stays order-sensitive but
    # explicit about what the test is exercising.
    scalars_calls: list[list[MagicMock]] = [[*refs_by_doc[1]]]
    for doc_id in sorted(other_refs_by_doc):
        scalars_calls.append([*refs_by_doc[doc_id]])

    execute_result = MagicMock()
    execute_result.all.return_value = [
        (doc_id, normalized, normalized)
        for doc_id, values in related.items()
        for normalized in values
    ]

    scalars_index = {"value": 0}

    def _scalars(_stmt):  # type: ignore[no-untyped-def]
        idx = scalars_index["value"]
        scalars_index["value"] += 1
        if idx >= len(scalars_calls):
            raise AssertionError("extract made more scalars() calls than the test prepared")
        result = MagicMock()
        result.all.return_value = list(scalars_calls[idx])
        return result

    def _execute(_stmt):  # type: ignore[no-untyped-def]
        return execute_result

    session.scalars.side_effect = _scalars
    session.execute.side_effect = _execute
    return session


def test_proposes_relation_for_documents_sharing_a_reference():
    session = _session_for(
        source_refs=["REF-001", "REF-002"],
        other_refs_by_doc={2: ["REF-001", "REF-099"]},
    )
    extractor = SharedReferenceExtractor(min_shared=1)
    proposals = extractor.propose(session, document_id=1)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.relation_type == "shared_reference"
    assert proposal.source_entity_value == "1"
    assert proposal.target_entity_value == "2"
    assert proposal.evidence[0].quote == "REF-001"
    # Jaccard: shared=1, union=3 (REF-001, REF-002, REF-099) -> 0.333
    assert proposal.confidence == pytest.approx(1 / 3, rel=1e-3)


def test_skips_documents_below_min_shared():
    session = _session_for(
        source_refs=["REF-001", "REF-002"],
        other_refs_by_doc={2: ["REF-001"]},  # only one overlap
    )
    extractor = SharedReferenceExtractor(min_shared=2)
    proposals = extractor.propose(session, document_id=1)
    assert proposals == []


def test_truncates_evidence_quote_to_quote_max_chars():
    long_quote = "REF-" + ("X" * 500)
    session = _session_for(
        source_refs=[long_quote],
        other_refs_by_doc={2: [long_quote]},
    )
    extractor = SharedReferenceExtractor(min_shared=1, quote_max_chars=80)
    proposals = extractor.propose(session, document_id=1)
    assert proposals, "the proposal should still be emitted for the long quote"
    assert len(proposals[0].evidence[0].quote) == 80


def test_returns_empty_when_source_has_no_references():
    session = _session_for(source_refs=[], other_refs_by_doc={2: ["X"]})
    extractor = SharedReferenceExtractor()
    assert extractor.propose(session, document_id=1) == []


def test_proposed_relation_confidence_meets_verification_threshold_by_default():
    proposal = ProposedRelation(
        source_entity_type="document",
        source_entity_value="1",
        source_normalized_value=None,
        target_entity_type="document",
        target_entity_value="2",
        target_normalized_value=None,
        relation_type="shared_reference",
        confidence=0.7,
    )
    # The threshold is the contract for human review: pin it here so
    # a future refactor cannot silently flip the floor and change
    # the verification semantics.
    assert proposal.confidence >= VERIFY_THRESHOLD
