"""Tests for the RAG evaluation harness (S0.4).

The tests below are deliberately *deterministic*: they feed the
evaluator a hand-crafted list of ``RetrievalHit`` rows instead of
calling the real ``hybrid_search``. This keeps the test fast, free of
database / embedding-model dependencies, and easy to reason about.

The point is to lock the *scoring behaviour* — context recall,
answer relevancy, citation accuracy, the per-question gate, the
aggregate report — so future refactors of the evaluator cannot
silently change what we measure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.rag_evaluator import (
    GoldenQA,
    QuestionResult,
    RagEvalReport,
    RetrievalHit,
    answer_relevancy_from_keywords,
    citation_accuracy,
    context_recall_at_k,
    evaluate_retrieval,
    load_golden_qa,
    render_text_report,
)


# ---------------------------------------------------------------------------
# Unit tests for the scoring functions
# ---------------------------------------------------------------------------


def test_context_recall_at_k_returns_one_when_no_expected_documents():
    assert context_recall_at_k(expected=[], retrieved_doc_ids=[1, 2, 3]) == 1.0


def test_context_recall_at_k_returns_zero_when_no_retrieval():
    assert context_recall_at_k(expected=[1, 2], retrieved_doc_ids=[]) == 0.0


def test_context_recall_at_k_full_when_all_expected_found():
    assert context_recall_at_k(expected=[10, 20], retrieved_doc_ids=[10, 30, 20]) == 1.0


def test_context_recall_at_k_partial():
    # 2 of 3 expected documents are in the top-5.
    assert context_recall_at_k(expected=[10, 20, 30], retrieved_doc_ids=[10, 99, 20, 88, 77]) == pytest.approx(2 / 3)


def test_answer_relevancy_from_keywords_handles_empty_inputs():
    assert answer_relevancy_from_keywords(expected_keywords=[], retrieved_excerpts=["anything"]) == 1.0
    assert answer_relevancy_from_keywords(expected_keywords=["EUR"], retrieved_excerpts=[]) == 0.0


def test_answer_relevancy_from_keywords_is_case_insensitive_and_substring():
    excerpts = ["Total: 12,450 EUR", "Fecha: 2025-04-01", "Cliente: Garcia"]
    # 2 of 3 keywords present.
    assert answer_relevancy_from_keywords(
        expected_keywords=["eur", "garcia", "missing"],
        retrieved_excerpts=excerpts,
    ) == pytest.approx(2 / 3)


def test_citation_accuracy_credits_only_top_n():
    # Expected = [10, 20, 30]. Top-3 retrieved = [99, 98, 97] (none expected).
    assert citation_accuracy(expected=[10, 20, 30], retrieved_doc_ids=[99, 98, 97]) == 0.0
    # Top-3 = [10, 99, 20] (2 of 3 expected). Top-3 cap.
    assert citation_accuracy(expected=[10, 20, 30], retrieved_doc_ids=[10, 99, 20]) == pytest.approx(2 / 3)
    # Single expected doc at rank 1.
    assert citation_accuracy(expected=[10], retrieved_doc_ids=[10, 99, 20]) == 1.0


def test_citation_accuracy_handles_no_expected():
    assert citation_accuracy(expected=[], retrieved_doc_ids=[1, 2, 3]) == 1.0


# ---------------------------------------------------------------------------
# Golden-set loader
# ---------------------------------------------------------------------------


def test_load_golden_qa_parses_jsonl_with_comments(tmp_path: Path):
    file = tmp_path / "golden.jsonl"
    file.write_text(
        "# Header comment\n"
        "\n"
        '{"id": "q1", "category": "presupuesto", "question": "Total?"}\n'
        '{"id": "q2", "category": "pedido", "question": "Ultimo?", "expected_keywords": ["foo"]}\n',
        encoding="utf-8",
    )
    rows = load_golden_qa(file)
    assert len(rows) == 2
    assert rows[0].id == "q1"
    assert rows[0].expected_document_ids == []
    assert rows[0].expected_keywords == []
    assert rows[0].min_context_recall == 0.5  # default
    assert rows[1].expected_keywords == ["foo"]


def test_load_golden_qa_rejects_malformed_json(tmp_path: Path):
    file = tmp_path / "bad.jsonl"
    file.write_text('{"id": "q1", "question": "ok"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_golden_qa(file)


def test_load_golden_qa_rejects_missing_required_fields(tmp_path: Path):
    file = tmp_path / "missing.jsonl"
    file.write_text('{"id": "q1"}\n', encoding="utf-8")  # missing 'question'
    with pytest.raises(ValueError):
        load_golden_qa(file)


# ---------------------------------------------------------------------------
# evaluate_retrieval — end-to-end with a hand-crafted search_fn
# ---------------------------------------------------------------------------


def _hit(doc_id: int, score: float, excerpt: str = "") -> RetrievalHit:
    return RetrievalHit(document_id=doc_id, score=score, excerpt=excerpt)


def test_evaluate_retrieval_passes_when_recall_meets_gate():
    questions = [
        GoldenQA(
            id="q1",
            category="presupuesto",
            question="Total del presupuesto 245745?",
            expected_document_ids=[10, 20],
            expected_keywords=["245745", "EUR"],
            min_context_recall=0.5,
        )
    ]

    def search_fn(question: str):
        return [
            _hit(10, 0.95, "Presupuesto 245745 por importe 12.450 EUR"),
            _hit(20, 0.80, "Cliente: Acme"),
            _hit(99, 0.40, "irrelevante"),
        ]

    report = evaluate_retrieval(questions=questions, search_fn=search_fn, k=10)
    assert report.total == 1
    assert report.passed == 1
    assert report.failed == 0
    assert report.results[0].context_recall == 1.0
    assert report.results[0].answer_relevancy == 1.0
    assert report.results[0].citation_accuracy == 1.0


def test_evaluate_retrieval_fails_when_recall_below_gate():
    questions = [
        GoldenQA(
            id="q2",
            category="pedido",
            question="Pedido del proveedor Garcia?",
            expected_document_ids=[42],
            min_context_recall=0.9,
        )
    ]

    def search_fn(question: str):
        return [_hit(99, 0.5, "nada que ver")]

    report = evaluate_retrieval(questions=questions, search_fn=search_fn, k=10)
    assert report.passed == 0
    assert report.failed == 1
    assert "missed docs: [42]" in report.results[0].detail


def test_evaluate_retrieval_records_exception_in_detail():
    questions = [
        GoldenQA(id="q3", category="exploratory", question="algún error?"),
    ]

    def search_fn(question: str):
        raise RuntimeError("DB down")

    report = evaluate_retrieval(questions=questions, search_fn=search_fn, k=10)
    assert report.failed == 1
    assert "DB down" in report.results[0].detail


def test_evaluate_retrieval_aggregates_by_category():
    questions = [
        GoldenQA(id="q1", category="presupuesto", question="?", expected_document_ids=[1], min_context_recall=0.0),
        GoldenQA(id="q2", category="presupuesto", question="?", expected_document_ids=[2], min_context_recall=0.0),
        GoldenQA(id="q3", category="plano", question="?", expected_document_ids=[3], min_context_recall=0.0),
    ]

    def search_fn(question: str):
        return [_hit(1, 0.9), _hit(2, 0.8), _hit(3, 0.7)][:1]

    report = evaluate_retrieval(questions=questions, search_fn=search_fn, k=10)
    assert {agg.category for agg in report.category_aggregates} == {"presupuesto", "plano"}
    presupuesto = next(a for a in report.category_aggregates if a.category == "presupuesto")
    assert presupuesto.count == 2


def test_evaluate_retrieval_empty_golden_set_returns_empty_report():
    report = evaluate_retrieval(questions=[], search_fn=lambda q: [])
    assert report.total == 0
    assert report.passed == 0
    assert report.mean_context_recall == 0.0


# ---------------------------------------------------------------------------
# Text report rendering
# ---------------------------------------------------------------------------


def test_render_text_report_contains_aggregate_metrics():
    report = RagEvalReport(
        results=[],
        category_aggregates=[],
        total=0,
        passed=0,
        failed=0,
        mean_context_recall=0.5,
        mean_answer_relevancy=0.6,
        mean_citation_accuracy=0.7,
        min_context_recall=0.1,
        min_answer_relevancy=0.2,
        min_citation_accuracy=0.3,
    )
    text = render_text_report(report)
    assert "RAG EVALUATION REPORT" in text
    assert "context_recall" in text
    assert "0.500" in text


def test_render_text_report_lists_failing_questions():
    results = [
        QuestionResult(
            id="q1",
            category="presupuesto",
            question="Cual es el total?",
            context_recall=0.0,
            answer_relevancy=0.0,
            citation_accuracy=0.0,
            retrieved_document_ids=[],
            passed=False,
            detail="missed docs: [42]",
        )
    ]
    report = RagEvalReport(
        results=results,
        category_aggregates=[],
        total=1,
        passed=0,
        failed=1,
        mean_context_recall=0.0,
        mean_answer_relevancy=0.0,
        mean_citation_accuracy=0.0,
        min_context_recall=0.0,
        min_answer_relevancy=0.0,
        min_citation_accuracy=0.0,
    )
    text = render_text_report(report)
    assert "Failing questions" in text
    assert "q1" in text
    assert "missed docs: [42]" in text


# ---------------------------------------------------------------------------
# Integration: the real golden file in the repo is loadable.
# ---------------------------------------------------------------------------


def test_repo_golden_qa_file_is_loadable():
    """Smoke-test: the file shipped in tests/eval/golden_qa.jsonl must
    parse cleanly. If the file is broken (typo, missing comma) this
    fails loudly instead of crashing the CLI later."""
    repo_path = Path(__file__).resolve().parent / "eval" / "golden_qa.jsonl"
    if not repo_path.exists():
        pytest.skip("golden_qa.jsonl not present in this checkout")
    rows = load_golden_qa(repo_path)
    assert rows, "golden_qa.jsonl is empty"
    # Every row must have at least the required fields populated.
    for row in rows:
        assert row.id
        assert row.question
        assert row.category
        # min_context_recall is clamped by the dataclass type.
        assert 0.0 <= row.min_context_recall <= 1.0
