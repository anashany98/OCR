from app.ai.agent import build_grounded_response, select_tools_for_question
from app.services.embeddings import cosine_similarity, embed_text
from app.services import search_service
from app.services.search_service import SearchResult, merge_hybrid_results


def test_local_embedding_is_1024_dimensional_and_semantically_useful():
    query_vector = embed_text("pedido referencia ABC123")
    related_vector = embed_text("Lineas del pedido con referencia ABC123")
    unrelated_vector = embed_text("plano salon escala y superficie")

    assert len(query_vector) == 1024
    assert cosine_similarity(query_vector, related_vector) > cosine_similarity(query_vector, unrelated_vector)


def test_search_semantic_uses_query_embedding_role(monkeypatch):
    calls: list[str] = []

    class _FakePgvectorStore:
        def search(self, db, *, query_embedding, limit, filters):
            assert query_embedding == [0.4, 0.3, 0.2, 0.1]
            return []

    monkeypatch.setattr(search_service.cache_service, "get", lambda key: None)
    monkeypatch.setattr(search_service.cache_service, "set", lambda key, value, ttl_seconds: True)
    monkeypatch.setattr(search_service, "_is_postgres", lambda db: True)
    monkeypatch.setattr(search_service, "PgvectorStore", lambda: _FakePgvectorStore())
    monkeypatch.setattr(
        search_service,
        "embed_query_text",
        lambda text: calls.append(text) or [0.4, 0.3, 0.2, 0.1],
        raising=False,
    )

    assert search_service.search_semantic(db=object(), query="  total factura  ", limit=3) == []
    assert calls == ["total factura"]


def test_hybrid_merge_deduplicates_sources_with_rrf_score():
    text_result = SearchResult(
        document_id=7,
        original_filename="pedido_154.pdf",
        document_type="pedido",
        status="processed",
        page_number=1,
        block_id=None,
        score=1.0,
        excerpt="Pedido 2026/154 referencia ABC123",
        ocr_confidence=0.91,
    )
    semantic_result = SearchResult(
        document_id=7,
        original_filename="pedido_154.pdf",
        document_type="pedido",
        status="processed",
        page_number=1,
        block_id=None,
        score=0.82,
        excerpt="Pedido 2026/154 referencia ABC123",
        ocr_confidence=0.91,
    )

    merged = merge_hybrid_results([text_result], [semantic_result], limit=5)

    assert len(merged) == 1
    assert merged[0].source_type == "hybrid_rrf"
    assert merged[0].score == 2 / 61


def test_hybrid_rrf_allows_semantic_rank_to_beat_lower_text_rank():
    text_results = [
        SearchResult(
            document_id=1,
            original_filename="lexico_fuerte.pdf",
            document_type="factura",
            status="processed",
            page_number=1,
            block_id=None,
            score=1.0,
            excerpt="Factura",
            ocr_confidence=0.8,
        ),
        SearchResult(
            document_id=2,
            original_filename="lexico_debil.pdf",
            document_type="factura",
            status="processed",
            page_number=1,
            block_id=None,
            score=1.0,
            excerpt="Factura",
            ocr_confidence=0.8,
        ),
    ]
    semantic_results = [
        SearchResult(
            document_id=3,
            original_filename="semantico_relevante.pdf",
            document_type="factura",
            status="processed",
            page_number=4,
            block_id=None,
            score=0.94,
            excerpt="Base imponible y total de mayo",
            ocr_confidence=None,
            source_type="semantic_chunk",
        )
    ]

    merged = merge_hybrid_results(text_results, semantic_results, limit=2)

    assert [item.document_id for item in merged] == [1, 3]


def test_ai_agent_selects_only_controlled_tools_for_common_intents():
    assert select_tools_for_question("Que presupuestos aceptados no tienen pedido a proveedor?")[0].name == (
        "get_accepted_budgets_without_order"
    )
    assert select_tools_for_question("Ensenyame las lineas del pedido 2026/154")[0].name == "get_order_by_number"
    assert select_tools_for_question("Que documentos mencionan la referencia ABC123?")[0].name == "hybrid_search"
    assert select_tools_for_question("Cuanto mide el salon segun el plano?")[0].name == "search_plan_room_measurements"


def test_grounded_response_uses_required_sections_and_refuses_without_data():
    response = build_grounded_response(question="Cuanto mide el salon?", context_items=[], warnings=[])

    assert "No he encontrado informacion en el sistema" in response.answer
    assert "Respuesta:" not in response.answer
    assert "Fuentes:" not in response.answer
    assert response.confidence == 0.0
