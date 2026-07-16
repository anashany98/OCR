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


def test_fuzzy_subject_tolerates_one_typo_without_matching_similar_name():
    from app.ai.context import _search_result_matches_fuzzy_subject

    anibal = SimpleNamespace(
        original_filename="HOSTAL ANIBAL IBIZA.msg",
        source_path="upload/HOSTAL ANIBAL/Presupuesto 250398/IBIZA.msg",
        excerpt="Oferta para Hostal Anibal.",
        full_text=None,
    )
    anidac = SimpleNamespace(
        original_filename="HOSTAL ANIDAC IBIZA.msg",
        source_path="upload/HOSTAL ANIDAC/Presupuesto 252519/IBIZA.msg",
        excerpt="Oferta para Hostal Anidac.",
        full_text=None,
    )

    assert _search_result_matches_fuzzy_subject(anibal, ["hosal Anibal"]) is True
    assert _search_result_matches_fuzzy_subject(anidac, ["hosal Anibal"]) is False


def test_selector_reuses_all_bounded_documents_for_budget_followup():
    state = ActiveContext(last_retrieved_document_ids=list(range(1, 21)))

    tools = select_tools_for_question(
        "necesito el numero de presupuesto",
        active_context=state,
    )

    assert tools[0].name == "get_documents_by_ids"
    assert tools[0].arguments["document_ids"] == list(range(1, 13))


def test_selector_routes_visual_followup_to_image_backed_pages():
    state = ActiveContext(last_retrieved_document_ids=[10, 11, 12])

    tools = select_tools_for_question(
        "describeme las imagenes",
        active_context=state,
    )

    assert tools == [
        ToolCall(
            "get_documents_by_ids",
            {"document_ids": [10, 11, 12], "visual_only": True},
        )
    ]


def test_visual_subject_query_keeps_exact_subject_scope():
    tools = select_tools_for_question(
        "describeme las imagenes de hostal anibal",
        active_context=ActiveContext(),
    )

    assert tools == [
        ToolCall(
            "find_documents_by_exact_phrase",
            {"phrase": "hostal anibal", "visual_only": True},
        )
    ]


def test_grounded_followup_lists_budget_numbers_from_all_sources():
    from app.ai.context import ContextItem, build_grounded_response

    ordinal = chr(0xBA)
    context = [
        ContextItem(
            title="Documento de la conversacion: fase.msg",
            document_id=1,
            document_filename="fase.msg",
            summary="Ruta de carga: upload/Presupuesto 250398/fase.msg",
        ),
        ContextItem(
            title="Documento de la conversacion: correo.msg",
            document_id=2,
            document_filename="correo.msg",
            summary=f"Se mantiene el presupuesto {ordinal} 2649.",
        ),
        ContextItem(
            title="Documento de la conversacion: pedido.pdf",
            document_id=3,
            document_filename="pedido.pdf",
            summary="Ruta de carga: upload/Presupuesto 252519/pedido.pdf",
        ),
    ]

    response = build_grounded_response(
        question="necesito el numero de presupuesto",
        context_items=context,
        warnings=[],
    )

    assert "250398" in response.answer
    assert "252519" in response.answer
    assert "2649" in response.answer


def test_broad_model_answer_must_cite_three_retrieved_sources():
    from app.ai.context import ContextItem
    from app.ai.validation import response_covers_retrieved_sources

    items = [
        ContextItem(title=name, document_id=index, document_filename=name, summary="texto")
        for index, name in enumerate(("uno.msg", "dos.msg", "tres.msg"), start=1)
    ]

    assert response_covers_retrieved_sources(
        "Segun uno.msg y dos.msg hay informacion.", items, "Que sabes del proyecto?"
    ) is False
    assert response_covers_retrieved_sources(
        "Segun uno.msg, dos.msg y tres.msg hay informacion.", items, "Que sabes del proyecto?"
    ) is True
    # Narrow questions may legitimately answer from one of several sources.
    assert response_covers_retrieved_sources(
        "El total aparece en uno.msg.", items, "Cual es el total?"
    ) is True


def test_broad_model_answer_must_cover_multiple_sources_in_large_sets():
    from app.ai.context import ContextItem
    from app.ai.validation import response_covers_retrieved_sources

    items = [
        ContextItem(
            title=name,
            document_id=index,
            document_filename=name,
            summary="texto",
        )
        for index, name in enumerate((f"doc-{index}.msg" for index in range(1, 11)), start=1)
    ]

    two_sources = " ".join(f"doc-{index}.msg" for index in range(1, 3))
    three_sources = " ".join(f"doc-{index}.msg" for index in range(1, 4))
    assert response_covers_retrieved_sources(two_sources, items, "que mas me puedes decir") is False
    assert response_covers_retrieved_sources(three_sources, items, "que mas me puedes decir") is True


def test_validator_accepts_reference_number_from_attachment_label():
    from app.ai.context import ContextItem
    from app.ai.validation import response_fabricates_documents

    items = [
        ContextItem(
            title="Documento encontrado: RE_ Presupuesto Para hostal anibal.msg",
            document_id=1,
            document_filename="RE_ Presupuesto Para hostal anibal.msg",
            summary="Adjunto: 2649 PRESUPUESTO DECORACIONES EGEA HOSTAL ANIBAL.pdf",
        )
    ]

    assert response_fabricates_documents(
        "El presupuesto 2649 aparece en el correo.", items
    ) is False


def test_one_shot_uses_the_routed_model_injected_by_agent(monkeypatch):
    import asyncio

    from app.ai import agent
    from app.ai.context import ContextItem

    seen: dict[str, str] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update({key: str(value) for key, value in kwargs.items()})

        async def chat(self, messages, temperature=0.0, max_tokens=4000):
            return "Es un documento de prueba."

    monkeypatch.setattr(agent.settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(agent, "LocalOpenAICompatibleClient", FakeClient)
    answer = asyncio.run(
        agent._try_local_ai_answer(
            "Que es esto?",
            [
                ContextItem(
                    title="Documento de prueba",
                    document_id=1,
                    document_filename="prueba.pdf",
                    summary="Documento de prueba.",
                )
            ],
            [],
            fallback="fallback",
            model="qwen3-8b",
        )
    )

    assert answer == "Es un documento de prueba."
    assert seen["model"] == "qwen3-8b"


def test_visual_grounded_fallback_labels_pages_as_images():
    from app.ai.context import ContextItem, build_grounded_response

    items = [
        ContextItem(
            title=f"Imagen de la conversacion: {filename}, pagina {page}",
            document_id=index,
            document_filename=filename,
            page_number=page,
            summary="Descripcion visual de la pagina.",
        )
        for index, (filename, page) in enumerate(
            (("correo.msg", 2), ("fotos.pdf", 1), ("albaran.pdf", 1)),
            start=1,
        )
    ]

    response = build_grounded_response(
        question="describeme las imagenes",
        context_items=items,
        warnings=[],
    )

    assert "imagenes relacionadas" in response.answer
    assert "correo.msg, pagina 2" in response.answer
    assert "documentos relacionados" not in response.answer


def test_active_document_budget_followup_stays_on_that_document():
    state = ActiveContext(current_document_id=123456)
    question = "[Contexto: documento activo id=123456] por cuanto esta presupuestado"

    tools = select_tools_for_question(question, active_context=state)
    structured = select_structured_tools(question, active_context=state)

    assert [(tool.name, tool.arguments) for tool in tools] == [
        ("get_document_full_details", {"document_id": 123456})
    ]
    assert structured == []
