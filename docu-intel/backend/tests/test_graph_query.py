"""Unit tests for the Graph RAG read-side service and serializers.

The traversal (``list_relations_for_document`` /
``list_evidence_quotes``) is exercised against an in-memory
SQLAlchemy mock so the suite stays free of a live PostgreSQL.
The serializer helper (``_relation_row_to_read``) is tested
directly because it is the contract between the service
dataclass and the HTTP response.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _evidence(evidence_id: int = 1, quote: str = "REF-001", page_number: int | None = 2):
    return SimpleNamespace(
        id=evidence_id,
        relation_id=42,
        document_id=1,
        document_chunk_id=None,
        page_number=page_number,
        quote=quote,
        char_start=None,
        char_end=None,
        confidence=0.7,
        extractor_version="baseline-shared-reference-v1",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
    )


def _relation(relation_id: int = 42, status: str = "verified"):
    return SimpleNamespace(
        id=relation_id,
        source_entity_id=10,
        target_entity_id=20,
        relation_type="shared_reference",
        polarity="asserted",
        confidence=0.7,
        status=status,
        first_seen_at=datetime(2026, 7, 16, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 16, tzinfo=UTC),
    )


def _entity(entity_id: int, entity_type: str, value: str):
    return SimpleNamespace(
        id=entity_id,
        tenant_id=1,
        entity_type=entity_type,
        entity_value=value,
        normalized_value=None,
        canonical_label=None,
        language=None,
        first_seen_at=datetime(2026, 7, 16, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 16, tzinfo=UTC),
        mention_count=1,
    )


def _document(document_id: int = 1):
    return SimpleNamespace(id=document_id, deleted_at=None)


# ---------------------------------------------------------------------------
# list_relations_for_document
# ---------------------------------------------------------------------------


def test_list_relations_for_document_returns_empty_when_document_missing():
    from app.services import graph_query

    session = MagicMock()
    session.get.return_value = None
    assert graph_query.list_relations_for_document(session, 999) == []


def test_list_relations_for_document_returns_empty_when_no_mentions():
    from app.services import graph_query

    session = MagicMock()
    session.get.return_value = _document()

    # First call (mentions lookup) returns an empty result.
    mentions_result = MagicMock()
    mentions_result.all.return_value = []
    session.execute = MagicMock(return_value=mentions_result)

    assert graph_query.list_relations_for_document(session, 1) == []


def test_list_relations_for_document_joins_entities_and_evidence():
    from app.services import graph_query

    session = MagicMock()
    session.get.return_value = _document()

    relation = _relation()
    source = _entity(10, "document", "1")
    target = _entity(20, "document", "2")
    evidence = _evidence()

    # The service consumes four queries in this exact order:
    # 1) ``execute(...).all()``  → distinct entity mentions
    # 2) ``execute(...).scalars().all()`` → relations
    # 3) ``scalars(...).all()``  → entities (uses session.scalars directly)
    # 4) ``execute(...).scalars().all()`` → evidence rows
    mentions_result = MagicMock()
    mentions_result.all.return_value = [(10,)]

    relations_scalars = MagicMock()
    relations_scalars.all.return_value = [relation]
    relations_execute = MagicMock()
    relations_execute.scalars.return_value = relations_scalars

    entities_scalars = MagicMock()
    entities_scalars.all.return_value = [source, target]

    evidence_scalars = MagicMock()
    evidence_scalars.all.return_value = [evidence]
    evidence_execute = MagicMock()
    evidence_execute.scalars.return_value = evidence_scalars

    session.execute = MagicMock(
        side_effect=[mentions_result, relations_execute, evidence_execute]
    )
    session.scalars = MagicMock(return_value=entities_scalars)

    rows = graph_query.list_relations_for_document(session, 1)
    assert len(rows) == 1
    row = rows[0]
    assert row.relation_type == "shared_reference"
    assert row.source_entity_value == "1"
    assert row.target_entity_value == "2"
    assert row.evidence[0].quote == "REF-001"


# ---------------------------------------------------------------------------
# list_evidence_quotes
# ---------------------------------------------------------------------------


def test_list_evidence_quotes_returns_rows_in_descending_order():
    from app.services import graph_query

    session = MagicMock()
    session.get.return_value = _document()

    rows_fixture = [_evidence(evidence_id=1, quote="first"), _evidence(evidence_id=2, quote="second")]
    execute = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = list(rows_fixture)
    execute.scalars.return_value = scalars
    session.execute = MagicMock(return_value=execute)

    quotes = graph_query.list_evidence_quotes(session, 1)
    assert [item.evidence_id for item in quotes] == [1, 2]
    assert quotes[0].quote == "first"


# ---------------------------------------------------------------------------
# _relation_row_to_read (HTTP response serializer)
# ---------------------------------------------------------------------------


def test_relation_row_to_read_translates_dataclass_to_schema(monkeypatch):
    from app.api.routes import documents
    from app.services.graph_query import RelationEvidenceRow, RelationRow

    row = RelationRow(
        relation_id=42,
        relation_type="shared_reference",
        polarity="asserted",
        confidence=0.7,
        status="verified",
        source_entity_id=10,
        source_entity_type="document",
        source_entity_value="1",
        target_entity_id=20,
        target_entity_type="document",
        target_entity_value="2",
        evidence=[
            RelationEvidenceRow(
                evidence_id=1,
                relation_id=42,
                document_id=1,
                page_number=2,
                quote="REF-001",
                confidence=0.7,
                extractor_version="baseline-shared-reference-v1",
                created_at=datetime(2026, 7, 16, tzinfo=UTC),
            )
        ],
    )
    payload = documents._relation_row_to_read(row)
    assert payload.relation_id == 42
    assert payload.relation_type == "shared_reference"
    assert payload.source_entity_value == "1"
    assert payload.target_entity_value == "2"
    assert len(payload.evidence) == 1
    assert payload.evidence[0].quote == "REF-001"
    assert payload.evidence[0].extractor_version == "baseline-shared-reference-v1"
