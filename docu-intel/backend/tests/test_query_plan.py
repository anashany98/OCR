from app.ai.multi_query import build_query_plan
from app.core.config import settings


def test_exact_route_has_one_original_variant(monkeypatch):
    monkeypatch.setattr(settings, "search_multi_query_enabled", True)
    plan = build_query_plan(
        "importe del presupuesto 3987_001",
        tool_names={"get_budget_by_number", "hybrid_search"},
    )

    assert plan.strategy == "exact"
    assert [variant.text for variant in plan.variations] == ["importe del presupuesto 3987_001"]


def test_factual_route_stays_single_query_by_default(monkeypatch):
    monkeypatch.setattr(settings, "search_multi_query_enabled", True)
    monkeypatch.setattr(settings, "search_max_variants_factual", 1)

    plan = build_query_plan("quien es Aitor", tool_names={"hybrid_search"})

    assert plan.strategy == "factual"
    assert len(plan.variations) == 1


def test_synthesis_route_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "search_multi_query_enabled", True)
    monkeypatch.setattr(settings, "search_max_variants_synthesis", 2)

    plan = build_query_plan("compara los presupuestos", tool_names={"hybrid_search"})

    assert plan.strategy == "synthesis"
    assert 1 <= len(plan.variations) <= 2
