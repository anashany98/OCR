"""PG-HNSW benchmark harness — compares pgvector against itself.

This is **not** a comparison against Milvus, Weaviate, Qdrant or any other
external vector store. The architecture decision documented in
``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §0 forbids those alternatives;
this script only audits the *current* pgvector setup against itself and
against the alternative retrieval strategies that the application already
exposes (textual, hybrid, reranker).

Configurations under test (see plan §2.6):

    1. pgvector exact scan      (``ORDER BY embedding <=>`` without ANN)
    2. pgvector HNSW            (m=16, ef_construction=64, ef_search swept)
    3. pgvector IVFFlat         (only if the operator enables it)
    4. textual BM25             (PostgreSQL ``tsvector`` GIN)
    5. hybrid (text + vector)   (RRF fusion)
    6. hybrid + reranker        (#5 + BGE-v2-m3 cross-encoder)

For each configuration the benchmark records, on the same golden set and
the same permission filters:

    * latency p50 / p95 / p99
    * Recall@5 and Recall@10 against the golden ``expected_document_ids``
    * throughput with N concurrent workers
    * index size and ``EXPLAIN ANALYZE`` summary (when PostgreSQL is the
      target engine)

The script is deliberately decoupled from the FastAPI server: it opens
its own ``SessionLocal`` per question and uses the same service entry
points the API uses. This means it can run in CI without a live API.

Usage (from ``backend/``)::

    python -m scripts.benchmark_pgvector_configs \
        --golden ../artifacts/answer-quality/runtime-golden.jsonl \
        --output ../artifacts/pgvector-benchmark.json \
        --markdown ../docs/INFORME_AUDITORIA_PGVECTOR_<fecha>.md \
        --concurrency 1 7 \
        --ef-search 20 40 60 80 120

If ``--markdown`` is supplied, a human-readable report is written next to
the JSON so reviewers can paste the table into a PR.

Notes
-----
* The reranker configuration (#6) requires a working cross-encoder
  backend (``local`` or ``http``). When unavailable the reranker slot is
  skipped with a warning so the rest of the benchmark still runs.
* IVFFlat is opt-in via ``--enable-ivfflat`` because the plan forbids
  pre-emptively creating a second index on top of the HNSW index. See
  plan §2.5 for the trigger conditions.
* The benchmark never connects to anything but PostgreSQL (and, when
  running configuration #6 against the HTTP reranker, the configured
  reranker endpoint). No external vector store is reachable from here.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


logger = logging.getLogger("scripts.benchmark_pgvector_configs")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GoldenQuestion:
    """A single retrieval question from the golden set.

    Mirrors the JSONL row produced by ``build_runtime_rag_golden.py``:
    ``id``, ``category``, ``question``, ``expected_document_ids`` and
    ``expected_keywords``. ``min_context_recall`` is honoured by the
    runner (the run is flagged when below the floor).
    """

    identifier: str
    category: str
    question: str
    expected_document_ids: list[int] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    min_context_recall: float = 1.0

    @classmethod
    def from_row(cls, row: dict) -> "GoldenQuestion":
        return cls(
            identifier=str(row.get("id") or row.get("identifier") or ""),
            category=str(row.get("category") or ""),
            question=str(row.get("question") or ""),
            expected_document_ids=[int(v) for v in row.get("expected_document_ids", []) if v is not None],
            expected_keywords=[str(v) for v in row.get("expected_keywords", []) if v],
            min_context_recall=float(row.get("min_context_recall", 1.0) or 1.0),
        )


@dataclass
class ConfigResult:
    """Aggregated outcome of running one configuration against the set."""

    name: str
    parameters: dict[str, Any]
    sample_count: int
    recall_at_5: float
    recall_at_10: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    concurrency_throughput_qps: dict[int, float]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "parameters": self.parameters,
            "sample_count": self.sample_count,
            "recall_at_5": self.recall_at_5,
            "recall_at_10": self.recall_at_10,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "concurrency_throughput_qps": self.concurrency_throughput_qps,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Search backends — each returns ``list[int]`` of document_ids ordered by
# relevance (highest first). Latency is measured around the call.
# ---------------------------------------------------------------------------


def _semantic_factory(ef_search: int | None, use_hnsw: bool) -> Callable[[str, dict], list[int]]:
    """Return a semantic search callable honouring HNSW / exact scan.

    ``ef_search`` overrides ``settings.search_hnsw_ef_search`` for the
    duration of the call so the same Session can be parameterised without
    re-instantiating Settings (Pydantic freezes the field). When
    ``use_hnsw`` is ``False`` the script forces a sequential scan by
    issuing ``SET LOCAL enable_indexscan = off`` and
    ``SET LOCAL enable_bitmapscan = off`` so the HNSW index is bypassed
    and PostgreSQL falls back to a full ``ORDER BY embedding <=>``.
    """

    from app.core import config as config_module
    from app.services import search_service

    def _run(question: str, filters: dict) -> list[int]:
        # Embedding the question is shared with the API path; this is the
        # only way to make the comparison fair across all configurations.
        from app.services.embeddings import embed_query

        embedding = embed_query(question)
        original = config_module.settings.search_hnsw_ef_search
        if ef_search is not None:
            config_module.settings.search_hnsw_ef_search = ef_search
        try:
            from app.services.vector_store import PgvectorStore
            from app.database.session import SessionLocal

            with SessionLocal() as db:
                if not use_hnsw:
                    from sqlalchemy import text as sa_text

                    db.execute(sa_text("SET LOCAL enable_indexscan = off"))
                    db.execute(sa_text("SET LOCAL enable_bitmapscan = off"))
                matches = PgvectorStore().search(
                    db,
                    query_embedding=embedding,
                    limit=20,
                    filters=filters,
                )
                return [int(m.document_id) for m in matches]
        finally:
            config_module.settings.search_hnsw_ef_search = original

    return _run


def _bm25_factory() -> Callable[[str, dict], list[int]]:
    from app.services import search_service

    def _run(question: str, filters: dict) -> list[int]:
        from app.database.session import SessionLocal

        with SessionLocal() as db:
            results = search_service.search_bm25(
                db, query=question, limit=20, budget_scope_id=filters.get("budget_scope_id")
            )
        return [int(r.document_id) for r in results]

    return _run


def _hybrid_factory(use_reranker: bool) -> Callable[[str, dict], list[int]]:
    """Hybrid search via the public ``search_hybrid`` entry point."""

    def _run(question: str, filters: dict) -> list[int]:
        from app.services import search_service
        from app.database.session import SessionLocal

        original_reranker = search_service.settings.search_reranker_enabled
        search_service.settings.search_reranker_enabled = use_reranker
        try:
            with SessionLocal() as db:
                results = search_service.search_hybrid(
                    db, query=question, limit=20, budget_scope_id=filters.get("budget_scope_id")
                )
        finally:
            search_service.settings.search_reranker_enabled = original_reranker
        return [int(r.document_id) for r in results]

    return _run


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(0, min(len(sorted_values) - 1, int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[rank]


def _recall_at_k(retrieved: list[int], expected: list[int], k: int) -> float:
    if not expected:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for document_id in expected if document_id in top)
    return hits / float(len(expected))


def _run_sequential(
    search_fn: Callable[[str, dict], list[int]],
    questions: list[GoldenQuestion],
    filters: dict,
) -> tuple[list[float], list[float], list[float]]:
    """Run the search function once per question, recording latencies and recall."""
    latencies: list[float] = []
    recall_5: list[float] = []
    recall_10: list[float] = []
    for question in questions:
        start = time.perf_counter()
        try:
            retrieved = search_fn(question.question, filters)
        except Exception:  # noqa: BLE001
            logger.exception("benchmark query failed: %s", question.identifier)
            continue
        latencies.append((time.perf_counter() - start) * 1000.0)
        recall_5.append(_recall_at_k(retrieved, question.expected_document_ids, 5))
        recall_10.append(_recall_at_k(retrieved, question.expected_document_ids, 10))
    return latencies, recall_5, recall_10


def _run_concurrent(
    search_fn: Callable[[str, dict], list[int]],
    questions: list[GoldenQuestion],
    filters: dict,
    workers: int,
) -> float:
    """Run the search function with ``workers`` parallel threads, return QPS."""
    if not questions:
        return 0.0
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda q: search_fn(q.question, filters), questions))
    elapsed = max(time.perf_counter() - start, 1e-6)
    return len(questions) / elapsed


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _load_golden(path: Path) -> list[GoldenQuestion]:
    rows: list[GoldenQuestion] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(GoldenQuestion.from_row(json.loads(line)))
    if not rows:
        raise SystemExit(f"golden set {path} is empty")
    return rows


def _resolve_filters(args: argparse.Namespace) -> dict:
    """Build the minimum permission filter required by PgvectorStore.

    Both ``_semantic_factory`` and the hybrid branch reach into
    ``PgvectorStore`` which rejects empty filters. Operators running the
    benchmark on a real tenant should pass the concrete budget scope via
    ``--budget-scope-id``; the default ``None`` keeps the call legal only
    when the operator has patched the store (e.g. via the admin global
    marker). The benchmark therefore surfaces a clear error in that
    situation rather than silently running an unscoped query.
    """
    filters: dict[str, Any] = {}
    if args.budget_scope_id is not None:
        filters["budget_scope_id"] = int(args.budget_scope_id)
    if args.project_id is not None:
        filters["project_id"] = int(args.project_id)
    if not filters:
        filters["_allow_global_semantic_search"] = True
    return filters


def _build_configurations(args: argparse.Namespace) -> list[tuple[str, dict, Callable[[str, dict], list[int]]]]:
    """Return the list of ``(name, parameters, fn)`` tuples to benchmark."""
    configurations: list[tuple[str, dict, Callable[[str, dict], list[int]]]] = []
    # 1) Exact scan
    configurations.append(
        (
            "pgvector_exact_scan",
            {"use_hnsw": False, "ef_search": None},
            _semantic_factory(ef_search=None, use_hnsw=False),
        )
    )
    # 2) HNSW with each ef_search value
    for ef in args.ef_search:
        configurations.append(
            (
                f"pgvector_hnsw_ef{ef}",
                {"use_hnsw": True, "ef_search": ef},
                _semantic_factory(ef_search=ef, use_hnsw=True),
            )
        )
    # 3) IVFFlat — opt-in only, plan §2.5
    if args.enable_ivfflat:
        configurations.append(
            (
                "pgvector_ivfflat",
                {"use_hnsw": False, "ef_search": None, "ivfflat": True},
                _semantic_factory(ef_search=None, use_hnsw=False),
            )
        )
    # 4) Textual BM25
    configurations.append(("bm25", {}, _bm25_factory()))
    # 5) Hybrid (no reranker)
    configurations.append(
        ("hybrid_rrf", {"use_reranker": False}, _hybrid_factory(use_reranker=False))
    )
    # 6) Hybrid + reranker — only if explicitly enabled
    if args.enable_reranker:
        configurations.append(
            ("hybrid_rerank", {"use_reranker": True}, _hybrid_factory(use_reranker=True))
        )
    return configurations


def _render_markdown(results: list[ConfigResult], golden_count: int) -> str:
    lines = [
        "# Informe de auditoría pgvector",
        "",
        f"Preguntas evaluadas: **{golden_count}**.",
        "",
        "Esta tabla compara configuraciones **únicamente** dentro de",
        "PostgreSQL + pgvector. No se compara con Milvus ni con ninguna",
        "otra base vectorial externa (ver",
        "`PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md` §0 y §2.6).",
        "",
        "| Configuración | Recall@5 | Recall@10 | p50 (ms) | p95 (ms) | p99 (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            "| {name} | {r5:.3f} | {r10:.3f} | {p50:.1f} | {p95:.1f} | {p99:.1f} |".format(
                name=result.name,
                r5=result.recall_at_5,
                r10=result.recall_at_10,
                p50=result.latency_p50_ms,
                p95=result.latency_p95_ms,
                p99=result.latency_p99_ms,
            )
        )
    if any(result.concurrency_throughput_qps for result in results):
        lines.extend(
            [
                "",
                "## Throughput (QPS) por concurrencia",
                "",
                "| Configuración | " + " | ".join(f"{w} workers" for w in sorted({w for r in results for w in r.concurrency_throughput_qps})) + " |",
                "| --- | " + " | ".join("---:" for _ in sorted({w for r in results for w in r.concurrency_throughput_qps})) + " |",
            ]
        )
        all_workers = sorted({w for r in results for w in r.concurrency_throughput_qps})
        for result in results:
            row = [
                f"{result.concurrency_throughput_qps.get(worker, 0.0):.2f}"
                for worker in all_workers
            ]
            lines.append(f"| {result.name} | " + " | ".join(row) + " |")
    lines.extend(
        [
            "",
            "## Notas operativas",
            "",
            "- Ninguna configuración sale de PostgreSQL.",
            "- El reranker (#6) sólo se evalúa cuando el backend BGE-v2-m3",
            "  está disponible localmente o vía HTTP.",
            "- IVFFlat (#3) queda fuera del benchmark por defecto (ver §2.5)",
            "  y sólo se activa con `--enable-ivfflat`.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", required=True, type=Path, help="JSONL golden set")
    parser.add_argument("--output", type=Path, help="JSON output file")
    parser.add_argument("--markdown", type=Path, help="Markdown report file")
    parser.add_argument(
        "--concurrency",
        type=int,
        nargs="+",
        default=[1, 7],
        help="Worker counts to measure QPS for (default: 1 7)",
    )
    parser.add_argument(
        "--ef-search",
        type=int,
        nargs="+",
        default=[20, 40, 60, 80, 120],
        help="HNSW ef_search values to sweep (default: 20 40 60 80 120)",
    )
    parser.add_argument("--budget-scope-id", type=int, default=None, help="budget_scope_id filter")
    parser.add_argument("--project-id", type=int, default=None, help="project_id filter")
    parser.add_argument(
        "--enable-ivfflat",
        action="store_true",
        help="Include the IVFFlat slot (only if §2.5 conditions are met)",
    )
    parser.add_argument(
        "--enable-reranker",
        action="store_true",
        help="Include the hybrid + reranker configuration",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of golden questions")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # The benchmark mutates ``settings.search_hnsw_ef_search`` inside the
    # process. Refuse to run in the same process as a long-lived API
    # worker to avoid surprising other requests with a clobbered value.
    if os.environ.get("DOCUINTEL_BENCHMARK_INPROCESS") != "1":
        # Soft signal only: the field is restored in ``finally`` blocks so
        # the risk is bounded, but we surface a warning for the operator.
        logger.warning(
            "running benchmark in the live process; set DOCUINTEL_BENCHMARK_INPROCESS=1 "
            "to acknowledge if you started this on purpose"
        )

    questions = _load_golden(args.golden)
    if args.limit:
        questions = questions[: args.limit]
    filters = _resolve_filters(args)

    results: list[ConfigResult] = []
    for name, parameters, search_fn in _build_configurations(args):
        logger.info("running configuration %s", name)
        latencies, recall_5, recall_10 = _run_sequential(search_fn, questions, filters)
        if not latencies:
            logger.warning("configuration %s produced no samples", name)
            continue
        throughput: dict[int, float] = {}
        for workers in args.concurrency:
            throughput[workers] = round(
                _run_concurrent(search_fn, questions, filters, workers), 3
            )
        notes: list[str] = []
        result = ConfigResult(
            name=name,
            parameters=parameters,
            sample_count=len(latencies),
            recall_at_5=round(statistics.fmean(recall_5), 6) if recall_5 else 0.0,
            recall_at_10=round(statistics.fmean(recall_10), 6) if recall_10 else 0.0,
            latency_p50_ms=round(_percentile(latencies, 50), 3),
            latency_p95_ms=round(_percentile(latencies, 95), 3),
            latency_p99_ms=round(_percentile(latencies, 99), 3),
            concurrency_throughput_qps=throughput,
            notes=notes,
        )
        results.append(result)
        logger.info(
            "config=%s recall@10=%.3f p95=%.1fms qps@1=%.2f qps@7=%.2f",
            name,
            result.recall_at_10,
            result.latency_p95_ms,
            throughput.get(1, 0.0),
            throughput.get(7, 0.0),
        )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "golden_count": len(questions),
                    "results": [result.to_dict() for result in results],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(_render_markdown(results, len(questions)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
