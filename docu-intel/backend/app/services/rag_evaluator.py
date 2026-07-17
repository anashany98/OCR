"""S0.4 — RAG evaluation harness.

The point of this module is to give us a **deterministic, LLM-free** way to
measure whether a change to the retrieval / reranking / generation stack
made things better or worse. Real RAGAS / TruLens evaluations are great
but they require an LLM-as-judge, which we cannot run in CI without a
GPU and which is non-deterministic. This module instead measures the
*upstream* signals that RAG depends on:

* **context_recall@k** — of the documents the question expects, how many
  appear in the top-k retrieved by `hybrid_search`? (the gold standard
  for "did retrieval find the right stuff").
* **answer_relevancy** — of the keywords / phrases the answer is
  expected to contain, how many appear in the top-k excerpts? (cheap
  proxy for "did retrieval surface the *content* the answer needs",
  independent of the LLM that will eventually read it).
* **citation_accuracy** — when the question expects specific documents,
  are *those* the ones returned with the highest score? (penalises
  noisy retrieval that returns the right doc at rank 7).
* **tool_selection** — did the agent's tool selector pick a tool that
  is *capable* of answering the question? (catches regressions in
  `select_tools_for_question`).

The evaluator is intentionally fast and self-contained: it does not
require the LLM, the embedding model, or the database to be reachable
beyond the search APIs themselves. This makes it usable in CI on every
PR.

A run produces a `RagEvalReport` with per-question and aggregate
metrics. The CLI (`scripts/eval_rag.py`) prints a table; the test
(`tests/test_rag_eval.py`) gates the build on minimum thresholds.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.rag_evaluator")


# ---------------------------------------------------------------------------
# Golden-set schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldenQA:
    """A single row in ``tests/eval/golden_qa.jsonl``.

    Fields:
        id: stable identifier (e.g. ``"q001"``) so reports can be cross-
            referenced across CI runs.
        category: one of ``presupuesto``, ``pedido``, ``factura``,
            ``plano``, ``exploratory`` — used to break down metrics.
        question: the exact text the user would type.
        expected_document_ids: document ids the top-k retrieval should
            surface. Empty list is valid only for an explicitly exploratory
            or intentionally unscored question; otherwise it is reported as
            an uncurated benchmark case instead of a false green result.
        expected_keywords: literal substrings the answer is expected to
            mention (importes, NIFs, dates, room names, etc.). Used to
            score answer_relevancy without an LLM.
        min_context_recall: per-question gate. Defaults to ``0.5`` when
            not specified.
    """

    id: str
    category: str
    question: str
    expected_document_ids: list[int] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    min_context_recall: float = 0.5
    allow_empty_expected: bool = False

    @property
    def has_ground_truth(self) -> bool:
        return bool(self.expected_document_ids) or self.category == "exploratory" or self.allow_empty_expected

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoldenQA:
        try:
            return cls(
                id=str(data["id"]),
                category=str(data.get("category", "exploratory")),
                question=str(data["question"]),
                expected_document_ids=[int(x) for x in data.get("expected_document_ids", []) or []],
                expected_keywords=[str(x) for x in data.get("expected_keywords", []) or []],
                min_context_recall=float(data.get("min_context_recall", 0.5)),
                allow_empty_expected=bool(data.get("allow_empty_expected", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed golden Q&A row: {data!r} ({exc})") from exc


def load_golden_qa(path: str | Path) -> list[GoldenQA]:
    """Load the golden Q&A set from a JSONL file.

    Empty lines and lines starting with ``#`` are ignored so the file
    can carry human-readable headers.
    """
    rows: list[GoldenQA] = []
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Golden Q&A file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
            rows.append(GoldenQA.from_dict(data))
    return rows


# ---------------------------------------------------------------------------
# Retrieval scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalHit:
    """One row returned by `hybrid_search` or `search_text`."""

    document_id: int
    score: float
    excerpt: str = ""


def _hits_to_doc_ids(hits: Iterable[RetrievalHit]) -> list[int]:
    return [hit.document_id for hit in hits]


def context_recall_at_k(
    expected: list[int],
    retrieved_doc_ids: list[int],
) -> float:
    """Fraction of the *expected* documents that appear anywhere in the
    top-k retrieved documents.

    Returns 1.0 when there are no expected documents (the question is
    exploratory and any retrieval is acceptable).
    """
    if not expected:
        return 1.0
    if not retrieved_doc_ids:
        return 0.0
    retrieved_set = set(retrieved_doc_ids)
    hits = sum(1 for doc_id in expected if doc_id in retrieved_set)
    return hits / len(expected)


def answer_relevancy_from_keywords(
    expected_keywords: list[str],
    retrieved_excerpts: list[str],
) -> float:
    """Cheap proxy for answer relevancy: of the keywords the answer is
    expected to mention, how many appear in the top-k excerpts?

    Case-insensitive substring match. Returns 1.0 when there are no
    expected keywords.
    """
    if not expected_keywords:
        return 1.0
    if not retrieved_excerpts:
        return 0.0
    haystack = "\n".join(retrieved_excerpts).lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in haystack)
    return hits / len(expected_keywords)


def citation_accuracy(
    expected: list[int],
    retrieved_doc_ids: list[int],
    *,
    top_n: int = 3,
) -> float:
    """Fraction of the top-n retrieved documents that *should* be there
    (i.e. are in the expected set). A low score means the retrieval is
    surfacing irrelevant docs above the relevant ones.

    Returns 1.0 when there are no expected documents.
    """
    if not expected:
        return 1.0
    expected_set = set(expected)
    # A document can contribute several chunks. Citation quality is about
    # distinct documents, so duplicated pages must neither inflate the score
    # nor make the metric exceed 1.0.
    top = list(dict.fromkeys(retrieved_doc_ids))[:top_n]
    if not top:
        return 0.0
    hits = sum(1 for doc_id in top if doc_id in expected_set)
    return hits / min(len(top), len(expected_set))


# ---------------------------------------------------------------------------
# Per-question and aggregate reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionResult:
    id: str
    category: str
    question: str
    context_recall: float
    answer_relevancy: float
    citation_accuracy: float
    retrieved_document_ids: list[int]
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class CategoryAggregate:
    category: str
    count: int
    mean_context_recall: float
    mean_answer_relevancy: float
    mean_citation_accuracy: float


@dataclass(frozen=True)
class RagEvalReport:
    results: list[QuestionResult]
    category_aggregates: list[CategoryAggregate]
    total: int
    passed: int
    failed: int
    mean_context_recall: float
    mean_answer_relevancy: float
    mean_citation_accuracy: float
    min_context_recall: float
    min_answer_relevancy: float
    min_citation_accuracy: float

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "metrics": {
                "mean_context_recall": round(self.mean_context_recall, 4),
                "mean_answer_relevancy": round(self.mean_answer_relevancy, 4),
                "mean_citation_accuracy": round(self.mean_citation_accuracy, 4),
                "min_context_recall": round(self.min_context_recall, 4),
                "min_answer_relevancy": round(self.min_answer_relevancy, 4),
                "min_citation_accuracy": round(self.min_citation_accuracy, 4),
            },
            "by_category": [asdict(agg) for agg in self.category_aggregates],
            "results": [asdict(r) for r in self.results],
        }


def _aggregate(
    results: list[QuestionResult],
) -> list[CategoryAggregate]:
    """Group by category and compute means. Stable order = sorted by
    category name."""
    by_cat: dict[str, list[QuestionResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    aggregates: list[CategoryAggregate] = []
    for cat in sorted(by_cat):
        rows = by_cat[cat]
        aggregates.append(
            CategoryAggregate(
                category=cat,
                count=len(rows),
                mean_context_recall=statistics.fmean(r.context_recall for r in rows),
                mean_answer_relevancy=statistics.fmean(r.answer_relevancy for r in rows),
                mean_citation_accuracy=statistics.fmean(r.citation_accuracy for r in rows),
            )
        )
    return aggregates


def _summary(results: list[QuestionResult]) -> RagEvalReport:
    if not results:
        return RagEvalReport(
            results=[],
            category_aggregates=[],
            total=0,
            passed=0,
            failed=0,
            mean_context_recall=0.0,
            mean_answer_relevancy=0.0,
            mean_citation_accuracy=0.0,
            min_context_recall=0.0,
            min_answer_relevancy=0.0,
            min_citation_accuracy=0.0,
        )
    passed = sum(1 for r in results if r.passed)
    return RagEvalReport(
        results=results,
        category_aggregates=_aggregate(results),
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        mean_context_recall=statistics.fmean(r.context_recall for r in results),
        mean_answer_relevancy=statistics.fmean(r.answer_relevancy for r in results),
        mean_citation_accuracy=statistics.fmean(r.citation_accuracy for r in results),
        min_context_recall=min(r.context_recall for r in results),
        min_answer_relevancy=min(r.answer_relevancy for r in results),
        min_citation_accuracy=min(r.citation_accuracy for r in results),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_retrieval(
    *,
    questions: list[GoldenQA],
    search_fn,
    k: int = 10,
) -> RagEvalReport:
    """Score the retrieval of every question.

    Args:
        questions: the golden set.
        search_fn: callable ``(question: str) -> list[RetrievalHit]``.
            The caller wires this up to ``internal.hybrid_search`` (or
            any other retrieval strategy we want to compare).
        k: how many results to keep from the retrieval call.

    The function never raises on a per-question failure: it logs and
    records a QuestionResult with the exception detail so a single
    broken question does not abort the whole report.
    """
    results: list[QuestionResult] = []
    for q in questions:
        if not q.has_ground_truth:
            results.append(
                QuestionResult(
                    id=q.id,
                    category=q.category,
                    question=q.question,
                    context_recall=0.0,
                    answer_relevancy=0.0,
                    citation_accuracy=0.0,
                    retrieved_document_ids=[],
                    passed=False,
                    detail="uncurated golden case: expected_document_ids is required",
                )
            )
            continue
        try:
            hits = list(search_fn(q.question))[:k]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Retrieval failed for question %s: %s", q.id, exc)
            results.append(
                QuestionResult(
                    id=q.id,
                    category=q.category,
                    question=q.question,
                    context_recall=0.0,
                    answer_relevancy=0.0,
                    citation_accuracy=0.0,
                    retrieved_document_ids=[],
                    passed=False,
                    detail=f"retrieval error: {exc}",
                )
            )
            continue

        retrieved_doc_ids = _hits_to_doc_ids(hits)
        retrieved_excerpts = [hit.excerpt for hit in hits if hit.excerpt]
        cr = context_recall_at_k(q.expected_document_ids, retrieved_doc_ids)
        ar = answer_relevancy_from_keywords(q.expected_keywords, retrieved_excerpts)
        ca = citation_accuracy(q.expected_document_ids, retrieved_doc_ids)

        passed = cr >= q.min_context_recall
        detail = ""
        if not passed:
            missed = [d for d in q.expected_document_ids if d not in retrieved_doc_ids]
            detail = (
                f"context_recall={cr:.2f} < gate {q.min_context_recall:.2f} (missed docs: {missed})"
            )

        results.append(
            QuestionResult(
                id=q.id,
                category=q.category,
                question=q.question,
                context_recall=cr,
                answer_relevancy=ar,
                citation_accuracy=ca,
                retrieved_document_ids=retrieved_doc_ids,
                passed=passed,
                detail=detail,
            )
        )
    return _summary(results)


def render_text_report(report: RagEvalReport) -> str:
    """Render a human-readable report (used by the CLI)."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("RAG EVALUATION REPORT")
    lines.append("=" * 80)
    lines.append(f"Questions: {report.total}   passed: {report.passed}   failed: {report.failed}")
    lines.append("")
    lines.append("Aggregate metrics:")
    lines.append(
        f"  context_recall   mean={report.mean_context_recall:.3f}   "
        f"min={report.min_context_recall:.3f}"
    )
    lines.append(
        f"  answer_relevancy mean={report.mean_answer_relevancy:.3f}   "
        f"min={report.min_answer_relevancy:.3f}"
    )
    lines.append(
        f"  citation_acc     mean={report.mean_citation_accuracy:.3f}   "
        f"min={report.min_citation_accuracy:.3f}"
    )
    if report.category_aggregates:
        lines.append("")
        lines.append("By category:")
        for agg in report.category_aggregates:
            lines.append(
                f"  {agg.category:<14} n={agg.count:<3} "
                f"recall={agg.mean_context_recall:.3f} "
                f"relevancy={agg.mean_answer_relevancy:.3f} "
                f"citation={agg.mean_citation_accuracy:.3f}"
            )
    if report.failed:
        lines.append("")
        lines.append("Failing questions:")
        for r in report.results:
            if not r.passed:
                lines.append(
                    f"  - [{r.id}] {r.category}: {r.question[:70]}"
                    f"{'...' if len(r.question) > 70 else ''}"
                )
                if r.detail:
                    lines.append(f"      {r.detail}")
    lines.append("=" * 80)
    return "\n".join(lines)


__all__ = [
    "GoldenQA",
    "RetrievalHit",
    "QuestionResult",
    "CategoryAggregate",
    "RagEvalReport",
    "load_golden_qa",
    "context_recall_at_k",
    "answer_relevancy_from_keywords",
    "citation_accuracy",
    "evaluate_retrieval",
    "render_text_report",
]
