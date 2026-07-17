"""Generate a retrieval golden set from the currently indexed corpus.

The main repository cannot safely commit database IDs: they change whenever
the corpus is rebuilt. This command creates a local JSONL baseline using the
live document IDs and stable, structured identifiers (budget/order/delivery
numbers) when available. Review the generated questions before using it as a
release gate.

Usage from ``backend/``::

    python -m scripts.build_runtime_rag_golden --output ../artifacts/answer-quality/runtime-golden.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _row(identifier: str, category: str, question: str, document_id: int, keywords: list[str]) -> dict:
    return {
        "id": identifier,
        "category": category,
        "question": question,
        "expected_document_ids": [document_id],
        "expected_keywords": keywords,
        "min_context_recall": 1.0,
    }


def build_rows(limit_per_category: int) -> list[dict]:
    from app.database.session import SessionLocal
    from app.models import Budget, DeliveryNote, Document, Order, Plan

    rows: list[dict] = []
    with SessionLocal() as db:
        budgets = list(
            db.scalars(
                select(Budget)
                .where(Budget.budget_number.is_not(None))
                .order_by(Budget.id.desc())
                .limit(limit_per_category)
            )
        )
        for budget in budgets:
            number = str(budget.budget_number).strip()
            rows.append(
                _row(
                    f"runtime-budget-{budget.id}",
                    "presupuesto",
                    f"Cual es el importe del presupuesto {number}?",
                    budget.document_id,
                    [number],
                )
            )

        orders = list(
            db.scalars(
                select(Order)
                .where(Order.order_number.is_not(None))
                .order_by(Order.id.desc())
                .limit(limit_per_category)
            )
        )
        for order in orders:
            number = str(order.order_number).strip()
            rows.append(
                _row(
                    f"runtime-order-{order.id}",
                    "pedido",
                    f"Que datos hay del pedido {number}?",
                    order.document_id,
                    [number],
                )
            )

        notes = list(
            db.scalars(
                select(DeliveryNote)
                .where(DeliveryNote.delivery_number.is_not(None))
                .order_by(DeliveryNote.id.desc())
                .limit(limit_per_category)
            )
        )
        for note in notes:
            number = str(note.delivery_number).strip()
            rows.append(
                _row(
                    f"runtime-delivery-{note.id}",
                    "albaran",
                    f"Que informacion hay del albaran {number}?",
                    note.document_id,
                    [number],
                )
            )

        plans = list(
            db.execute(
                select(Plan, Document)
                .join(Document, Document.id == Plan.document_id)
                .where((Plan.source_format.in_(("dxf", "dwg"))) | Plan.cad_unit.is_not(None))
                .order_by(Plan.id.desc())
                .limit(limit_per_category)
            ).all()
        )
        for plan, document in plans:
            filename = document.original_filename.strip()
            rows.append(
                _row(
                    f"runtime-plan-{plan.id}",
                    "plano",
                    f"Que datos estructurados tiene el plano {filename}?",
                    document.id,
                    [filename],
                )
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a live-corpus RAG golden set.")
    parser.add_argument("--output", required=True, help="Local JSONL output path.")
    parser.add_argument("--limit-per-category", type=int, default=5)
    args = parser.parse_args(argv)
    if args.limit_per_category < 1:
        parser.error("--limit-per-category must be positive")

    rows = build_rows(args.limit_per_category)
    if not rows:
        raise SystemExit("No structured documents available; ingest a corpus before building a golden set.")
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Generated from the live corpus. Review before promoting it to a release gate.\n"
        "# Regenerate after a destructive corpus reset; document IDs are intentionally runtime-specific.\n"
    )
    path.write_text(
        header + "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} curated retrieval cases to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
