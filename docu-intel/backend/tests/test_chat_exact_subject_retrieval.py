"""Regression tests for deterministic chat retrieval.

These cases reproduce the failure mode where a question about Hostal Anibal
could be answered with a similarly named Hostal Anidac document, and where
bare document numbers were sent to semantic retrieval.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.active_context import ActiveContext
from app.ai.context import collect_context
from app.ai.tools import ToolCall, select_structured_tools, select_tools_for_question
from app.database.base import Base
from app.models import Document, DocumentEntity, DocumentPage
from app.services.exact_document_search import search_exact_by_number, search_exact_phrase
from app.services.tenant_access import AccessScope


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def admin_scope() -> AccessScope:
    return AccessScope(principal_type="user", principal_id="admin", is_admin=True)


def _document(session: Session, filename: str, text: str) -> Document:
    document = Document(
        original_filename=filename,
        source_path=f"/data/{filename}",
        file_hash=f"hash-{filename}",
        status="processed",
        document_type="presupuesto",
    )
    session.add(document)
    session.flush()
    session.add(DocumentPage(document_id=document.id, page_number=1, text=text))
    return document


def test_exact_phrase_never_conflates_similar_hostal_names(db_session, admin_scope):
    anibal = _document(
        db_session,
        "HOSTAL ANIBAL IBIZA.msg",
        "Oferta para Hostal Anibal Ibiza, presupuesto 250398.",
    )
    _document(
        db_session,
        "HOSTAL ANIDAC IBIZA.msg",
        "Oferta para Hostal Anidac Ibiza, presupuesto 252519.",
    )
    db_session.commit()

    matches = search_exact_phrase(
        db_session,
        phrase="Hostal Anibal",
        access_scope=admin_scope,
    )

    assert [match.document_id for match in matches] == [anibal.id]
    assert matches[0].original_filename == "HOSTAL ANIBAL IBIZA.msg"


def test_exact_phrase_is_general_and_rejects_a_longer_project_name(db_session, admin_scope):
    costa_azul = _document(
        db_session,
        "PROYECTO COSTA AZUL.pdf",
        "Memoria de obra del Proyecto Costa Azul.",
    )
    _document(
        db_session,
        "PROYECTO COSTA AZULES.pdf",
        "Memoria de obra del Proyecto Costa Azules.",
    )
    db_session.commit()

    matches = search_exact_phrase(
        db_session,
        phrase="Proyecto Costa Azul",
        access_scope=admin_scope,
    )

    assert [match.document_id for match in matches] == [costa_azul.id]


def test_context_collector_keeps_the_exact_hostal_as_active_document(db_session, admin_scope):
    anibal = _document(
        db_session,
        "HOSTAL ANIBAL IBIZA.msg",
        "Oferta para Hostal Anibal Ibiza, presupuesto 250398.",
    )
    _document(
        db_session,
        "HOSTAL ANIDAC IBIZA.msg",
        "Oferta para Hostal Anidac Ibiza, presupuesto 252519.",
    )
    db_session.commit()

    context, warnings, resolved_doc_id = collect_context(
        db_session,
        [ToolCall("find_documents_by_exact_phrase", {"phrase": "Hostal Anibal"})],
        "Que sabes del Hostal Anibal?",
        access_scope=admin_scope,
    )

    assert resolved_doc_id == anibal.id
    assert len(context) == 1
    assert context[0].document_id == anibal.id
    assert "Anidac" not in context[0].summary
    assert warnings == []


def test_exact_number_rejects_a_longer_identifier(db_session, admin_scope):
    longer = _document(
        db_session,
        "presupuesto-12503980.pdf",
        "Numero de presupuesto 12503980.",
    )
    db_session.add(
        DocumentEntity(
            document_id=longer.id,
            entity_type="budget_number",
            entity_value="12503980",
        )
    )
    db_session.commit()

    assert search_exact_by_number(
        db_session,
        number="250398",
        kind="generic",
        access_scope=admin_scope,
    ) == []


def test_selector_searches_each_bare_identifier_exactly():
    tools = select_tools_for_question("Los numeros son 250398 y 252519")

    assert [(tool.name, tool.arguments["number"]) for tool in tools] == [
        ("find_document_by_exact_identifier", "250398"),
        ("find_document_by_exact_identifier", "252519"),
    ]


def test_selector_grounds_tax_and_prefixed_identifiers_literally():
    tax_tools = select_tools_for_question("Busca CIF B12345678")
    invoice_tools = select_tools_for_question("Factura F-2025-001")

    assert [(tool.name, tool.arguments) for tool in tax_tools] == [
        ("find_documents_by_exact_phrase", {"phrase": "B12345678"})
    ]
    assert [(tool.name, tool.arguments) for tool in invoice_tools] == [
        ("find_documents_by_exact_phrase", {"phrase": "F-2025-001"})
    ]


def test_selector_grounds_named_supplier_and_person_without_type_specific_rules():
    supplier_tools = select_tools_for_question("Que sabes del proveedor ACME Iberia?")
    person_tools = select_tools_for_question("Que sabes de Ana Perez?")

    assert [(tool.name, tool.arguments) for tool in supplier_tools] == [
        ("find_documents_by_exact_phrase", {"phrase": "proveedor ACME Iberia"})
    ]
    assert [(tool.name, tool.arguments) for tool in person_tools] == [
        ("find_documents_by_exact_phrase", {"phrase": "Ana Perez"})
    ]


def test_semantic_results_without_the_named_subject_are_rejected():
    from app.ai.context import _search_result_matches_exact_subject

    anibal = SimpleNamespace(
        original_filename="HOSTAL ANIBAL IBIZA.msg",
        source_path=None,
        excerpt="Oferta para el Hostal Anibal.",
        full_text=None,
    )
    anidac = SimpleNamespace(
        original_filename="HOSTAL ANIDAC IBIZA.msg",
        source_path=None,
        excerpt="Oferta para el Hostal Anidac.",
        full_text=None,
    )

    assert _search_result_matches_exact_subject(anibal, ["Hostal Anibal"]) is True
    assert _search_result_matches_exact_subject(anidac, ["Hostal Anibal"]) is False


def test_active_document_budget_followup_stays_on_that_document():
    state = ActiveContext(current_document_id=123456)
    question = "[Contexto: documento activo id=123456] por cuanto esta presupuestado"

    tools = select_tools_for_question(question, active_context=state)
    structured = select_structured_tools(question, active_context=state)

    assert [(tool.name, tool.arguments) for tool in tools] == [
        ("get_document_full_details", {"document_id": 123456})
    ]
    assert structured == []
