from app.ai.agent import build_grounded_response, select_tools_for_question
from app.services.embeddings import cosine_similarity, embed_text
from app.services.search_service import SearchResult, merge_hybrid_results


def test_local_embedding_is_1024_dimensional_and_semantically_useful():
    query_vector = embed_text("pedido referencia ABC123")
    related_vector = embed_text("Lineas del pedido con referencia ABC123")
    unrelated_vector = embed_text("plano salon escala y superficie")

    assert len(query_vector) == 1024
    assert cosine_similarity(query_vector, related_vector) > cosine_similarity(query_vector, unrelated_vector)


def test_hybrid_merge_deduplicates_sources_and_combines_scores():
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
    assert merged[0].score > text_result.score


def test_ai_agent_selects_only_controlled_tools_for_common_intents():
    assert select_tools_for_question("Que presupuestos aceptados no tienen pedido a proveedor?")[0].name == (
        "get_accepted_budgets_without_order"
    )
    assert select_tools_for_question("Ensenyame las lineas del pedido 2026/154")[0].name == "get_order_by_number"
    assert select_tools_for_question("Que documentos mencionan la referencia ABC123?")[0].name == "hybrid_search"
    assert select_tools_for_question("Cuanto mide el salon segun el plano?")[0].name == "search_plan_room_measurements"


def test_grounded_response_uses_required_sections_and_refuses_without_data():
    response = build_grounded_response(question="Cuanto mide el salon?", context_items=[], warnings=[])

    assert "Respuesta:" in response.answer
    assert "No puedo confirmarlo con la informacion disponible" in response.answer
    assert "Fuentes:" in response.answer
    assert response.confidence == 0.0
