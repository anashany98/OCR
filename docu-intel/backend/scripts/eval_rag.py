"""S0.4 — Run the RAG evaluation harness against the golden Q&A set.

Usage (from the backend/ directory):

    python -m scripts.eval_rag
    python -m scripts.eval_rag --golden tests/eval/golden_qa.jsonl
    python -m scripts.eval_rag --k 5 --json-out reports/rag.json
    python -m scripts.eval_rag --strategy hybrid      # default
    python -m scripts.eval_rag --strategy semantic
    python -m scripts.eval_rag --strategy text

Exit code is non-zero when the report flags any failure. This makes
the script usable as a CI gate: a regression in retrieval quality
breaks the build.

The script uses the project's SQLAlchemy session factory and the
``hybrid_search`` / ``search_semantic`` / ``search_text`` entry points
in ``app.services.search_service``. It is *not* safe to run while the
FastAPI app is up (it opens its own DB session per question) but it
does not require the API server.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the backend/ root is on sys.path so ``app.*`` imports work
# when the script is invoked from anywhere.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


logger = logging.getLogger("scripts.eval_rag")


def _build_search_fn(strategy: str):
    """Return a callable ``(question) -> list[RetrievalHit]`` for the
    selected retrieval strategy."""
    from app.services.rag_evaluator import RetrievalHit

    def hybrid(question: str):
        from app.tools.internal import hybrid_search

        results = hybrid_search(_SessionLocal(), question, {"limit": 20})
        return [
            RetrievalHit(
                document_id=r.document_id,
                score=r.score,
                excerpt=r.excerpt or "",
            )
            for r in results
        ]

    def semantic(question: str):
        from app.services.search_service import search_semantic

        results = search_semantic(_SessionLocal(), question, limit=20)
        return [
            RetrievalHit(
                document_id=r.document_id,
                score=r.score,
                excerpt=r.excerpt or "",
            )
            for r in results
        ]

    def text(question: str):
        from app.services.search_service import search_text

        results = search_text(_SessionLocal(), question, limit=20)
        return [
            RetrievalHit(
                document_id=r.document_id,
                score=r.score,
                excerpt=r.excerpt or "",
            )
            for r in results
        ]

    return {"hybrid": hybrid, "semantic": semantic, "text": text}[strategy]


def _SessionLocal():
    """Lazily build a SQLAlchemy session factory the first time we run."""
    global _SESSION_LOCAL
    if _SESSION_LOCAL is None:
        from app.database.session import SessionLocal  # type: ignore

        _SESSION_LOCAL = SessionLocal
    return _SESSION_LOCAL()


_SESSION_LOCAL = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAG evaluation harness.")
    parser.add_argument(
        "--golden",
        default=str(BACKEND_ROOT / "tests" / "eval" / "golden_qa.jsonl"),
        help="Path to the golden Q&A JSONL file.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="How many top-k results to keep from the retrieval call.",
    )
    parser.add_argument(
        "--strategy",
        choices=("hybrid", "semantic", "text"),
        default="hybrid",
        help="Which retrieval strategy to evaluate.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write the full report as JSON.",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit with non-zero status when any per-question gate fails.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from app.services.rag_evaluator import (
        evaluate_retrieval,
        load_golden_qa,
        render_text_report,
    )

    questions = load_golden_qa(args.golden)
    logger.info("Loaded %d questions from %s", len(questions), args.golden)
    if not questions:
        logger.error("Golden set is empty; nothing to evaluate.")
        return 2

    search_fn = _build_search_fn(args.strategy)
    report = evaluate_retrieval(questions=questions, search_fn=search_fn, k=args.k)

    print(render_text_report(report))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Wrote JSON report to %s", out_path)

    if args.fail_on_gate and report.failed:
        logger.error("%d/%d questions failed the per-question gate.", report.failed, report.total)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
