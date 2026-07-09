"""Recuperar documentos atascados/fallados y re-encolarlos.

Tres modos de recuperación (todos con --dry-run para previsualizar):

1. ``orphans``  — documentos en status='processing' cuyo último job ya está
   'failed' o no existe. BUG: tasks.py marcaba el job pero no el documento,
   dejándolo huérfano en 'processing' para siempre. Este modo los vuelve a
   encolar (el código que los mató ya está corregido).

2. ``failed``   — documentos con jobs fallados por errores TRANSITORIOS ya
   resueltos (AttributeError 'function' object has no attribute 'extract',
   ProgrammingError 'delivery_notes does not exist', NameError threading).
   El código actual los procesa sin problemas.

3. ``review``   — documentos en status='needs_review' por baja calidad de
    OCR. Útil tras arreglar PaddleOCR/PP-Structure para re-OCRizar con los
    motores ya funcionales y sacarlos de revisión.

4. ``desconocido`` — PDFs en status='desconocido' cuyo OCR está vacío
    (ocr_engine='empty') o es corrupto (<200 chars). Re-OCR completo para
    extraerles texto y permitir su clasificación.

Usage (dentro del contenedor backend):
    python scripts/recover_stuck_documents.py orphans     [--dry-run] [--limit N]
    python scripts/recover_stuck_documents.py failed      [--dry-run] [--limit N]
    python scripts/recover_stuck_documents.py review      [--dry-run] [--limit N]
    python scripts/recover_stuck_documents.py desconocido [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Document, ExtractionJob
from app.services.audit import write_audit

logger = logging.getLogger("recover_stuck")

# Errores transitorios ya corregidos cuyo job fallado es seguro re-encolar.
# Cualquier job cuyo error_message empiece por uno de estos prefijos se
# considera recuperable.
RECOVERABLE_ERROR_PREFIXES = (
    "AttributeError: 'function' object has no attribute 'extract'",
    "ProgrammingError: (psycopg.errors.UndefinedTable) relation \"delivery_notes\"",
    "NameError: name 'threading' is not defined",
)


def _has_active_job(db: Session, doc_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.document_id == doc_id)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
    )


def find_orphans(db: Session) -> list[int]:
    """Documentos en 'processing' cuyo último job NO está activo."""
    rows = db.execute(
        text("""
            SELECT d.id
            FROM documents d
            LEFT JOIN LATERAL (
                SELECT status FROM extraction_jobs ej
                WHERE ej.document_id = d.id
                ORDER BY ej.id DESC LIMIT 1
            ) j ON true
            WHERE d.status = 'processing'
              AND d.deleted_at IS NULL
              AND (j.status IS NULL OR j.status NOT IN ('pending', 'processing'))
            ORDER BY d.id
        """)
    ).scalars().all()
    return list(rows)


def find_recoverable_failed(db: Session) -> list[int]:
    """Documentos cuyo último job falló por un error transitorio ya corregido."""
    rows = db.execute(
        text("""
            SELECT DISTINCT d.id
            FROM documents d
            JOIN LATERAL (
                SELECT error_message, status FROM extraction_jobs ej
                WHERE ej.document_id = d.id
                ORDER BY ej.id DESC LIMIT 1
            ) j ON true
            WHERE j.status = 'failed'
              AND d.deleted_at IS NULL
              AND (
                j.error_message LIKE :a
                OR j.error_message LIKE :p
                OR j.error_message LIKE :n
              )
            ORDER BY d.id
        """),
        {
            "a": "AttributeError: 'function' object has no attribute 'extract'%",
            "p": 'ProgrammingError: (psycopg.errors.UndefinedTable) relation "delivery_notes"%',
            "n": "NameError: name 'threading' is not defined%",
        },
    ).scalars().all()
    return list(rows)


def find_review_for_reocr(db: Session) -> list[int]:
    """Documentos en 'needs_review' por baja calidad de OCR (recuperables con re-OCR).

    Usa CAST a jsonb porque quality_flags_json es tipo JSON (no JSONB) y el
    operador de containment ?| solo existe para jsonb.
    """
    rows = db.execute(
        text("""
            SELECT d.id
            FROM documents d
            WHERE d.status = 'needs_review'
              AND d.deleted_at IS NULL
              AND (
                d.quality_flags_json::jsonb ?| array['low_ocr_confidence',
                                                      'page_without_text',
                                                      'partial_low_ocr_confidence']
              )
            ORDER BY d.id
        """)
    ).scalars().all()
    return list(rows)


def find_desconocido_for_reocr(db: Session) -> list[int]:
    """PDFs 'desconocido' con OCR vacío (empty) o corrupto (<200 chars)."""
    rows = db.execute(
        text("""
            SELECT DISTINCT d.id
            FROM documents d
            JOIN document_pages dp ON dp.document_id = d.id
            WHERE d.document_type = 'desconocido'
              AND d.deleted_at IS NULL
              AND (
                dp.ocr_engine = 'empty'
                OR LENGTH(TRIM(COALESCE(dp.text, ''))) < 200
              )
            ORDER BY d.id
        """)
    ).scalars().all()
    return list(rows)


def enqueue_recovery(
    db: Session,
    document_ids: list[int],
    *,
    job_type: str,
    audit_action: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    """Re-encolar documentos: resetea estado + crea job + despacha tarea."""
    if limit is not None:
        document_ids = document_ids[:limit]

    enqueued = 0
    skipped = 0
    job_ids: list[int] = []

    for doc_id in document_ids:
        doc = db.get(Document, doc_id)
        if doc is None:
            skipped += 1
            continue
        if _has_active_job(db, doc_id):
            skipped += 1
            continue

        if dry_run:
            enqueued += 1
            continue

        # Resetear el documento al estado pendiente para que el worker lo
        # reprocese desde cero. Los flags de calidad se recalculan solos.
        doc.status = "pending"
        doc.quality_status = "pending"
        doc.quality_flags_json = []
        doc.error_message = None

        job = ExtractionJob(
            document_id=doc_id,
            job_type=job_type,
            status="pending",
        )
        db.add(job)
        db.flush()
        job_ids.append(job.id)

        from app.workers.routing import queue_for_document
        from app.workers.tasks import process_document_task

        process_document_task.apply_async(
            args=(doc_id, job.id),
            queue=queue_for_document(doc, job.job_type),
        )
        enqueued += 1

    if not dry_run and (enqueued or skipped):
        write_audit(
            db,
            user=None,
            action=audit_action,
            entity_type="operations",
            details={
                "mode": audit_action,
                "target_documents": len(document_ids),
                "enqueued": enqueued,
                "skipped": skipped,
            },
        )
        db.commit()

    return {
        "target_documents": len(document_ids),
        "enqueued": enqueued,
        "skipped": skipped,
        "job_ids": job_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recuperar documentos atascados/fallados")
    parser.add_argument(
        "mode",
        choices=["orphans", "failed", "review", "desconocido"],
        help="orphans: processing huérfanos | failed: jobs fallados recuperables | review: re-OCR de needs_review | desconocido: re-OCR de PDFs desconocido sin texto",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview sin encolar nada")
    parser.add_argument("--limit", type=int, default=500, help="Máximo de documentos (default 500)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.mode == "orphans":
            doc_ids = find_orphans(db)
            job_type = "reprocess:full"
            audit_action = "recover_orphan_processing"
        elif args.mode == "failed":
            doc_ids = find_recoverable_failed(db)
            job_type = "reprocess:full"
            audit_action = "recover_failed_transient"
        elif args.mode == "desconocido":
            doc_ids = find_desconocido_for_reocr(db)
            job_type = "reprocess:full"
            audit_action = "recover_desconocido_reocr"
        else:
            doc_ids = find_review_for_reocr(db)
            job_type = "reprocess:ocr"
            audit_action = "recover_review_reocr"

        print(f"Modo: {args.mode} | Documentos candidatos: {len(doc_ids)}")

        if not doc_ids:
            print("Nada que hacer.")
            return 0

        result = enqueue_recovery(
            db,
            doc_ids,
            job_type=job_type,
            audit_action=audit_action,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(f"Encolados: {result['enqueued']}")
        print(f"Saltados (job activo o doc eliminado): {result['skipped']}")
        if args.dry_run:
            print("(dry run — no se encoló nada)")
        else:
            jsample = result["job_ids"][:10]
            print(f"Primeros job IDs: {jsample}{'...' if len(result['job_ids']) > 10 else ''}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
