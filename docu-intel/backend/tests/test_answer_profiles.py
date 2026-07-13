from app.ai.answer_profiles import select_answer_profile


def test_exact_reference_uses_smallest_budget():
    profile = select_answer_profile("Cual es el importe del presupuesto 3987_001?")

    assert profile.name == "exact"
    assert profile.context_tokens == 1200
    assert profile.max_output_tokens == 256


def test_summary_and_synthesis_have_bounded_distinct_budgets():
    assert select_answer_profile("Resume este documento").name == "summary"
    profile = select_answer_profile("Compara los documentos y explica diferencias")
    assert profile.name == "synthesis"
    assert profile.max_output_tokens == 1800
