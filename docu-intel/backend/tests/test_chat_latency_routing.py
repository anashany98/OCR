from __future__ import annotations

from app.ai.tools import select_tools_for_question
from app.core.config import settings
from app.services.search_service import _use_multi_query_strategy


def test_exact_filename_avoids_hybrid_search_by_default() -> None:
    names = [tool.name for tool in select_tools_for_question("De que trata ppto firmado.jpeg?")]
    assert names == [
        "find_document_by_filename",
        "get_document_full_details",
        "get_related_documents",
    ]


def test_exact_number_avoids_hybrid_search_by_default() -> None:
    names = [tool.name for tool in select_tools_for_question("Cual es el presupuesto 3987_001?")]
    assert names == [
        "get_budget_by_number",
        "get_document_full_details",
        "get_related_documents",
    ]


def test_exact_first_can_be_rolled_back(monkeypatch) -> None:
    monkeypatch.setattr(settings, "search_exact_first_enabled", False)
    names = [tool.name for tool in select_tools_for_question("De que trata ppto firmado.jpeg?")]
    assert names[-1] == "hybrid_search"


def test_nested_semantic_expansion_is_off_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "search_use_query_transformer", True)
    monkeypatch.setattr(settings, "search_query_transform_strategy", "multi_query")
    monkeypatch.setattr(settings, "search_allow_nested_expansion", False)
    assert _use_multi_query_strategy() is False
