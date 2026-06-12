from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import ClassificationSuggestion, Document, LearnedPattern
from app.services.ai_cache import invalidate_all_ai_cache
from app.services.audit import write_audit
from app.services.classification import LearnedRule, classify_document
from app.services.webhooks import emit_classification_low_confidence, emit_new_pattern_detected
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
LOW_CONFIDENCE_THRESHOLD = 0.6


def _load_active_learned_rules(db: Session) -> list[LearnedRule]:
    rows = list(db.scalars(select(LearnedPattern).where(LearnedPattern.status == "active")).all())
    return [
        LearnedRule(
            pattern_value=row.pattern_value,
            target_class=row.target_class or "",
            confidence=row.confidence,
            source=f"learned:{row.id}",
        )
        for row in rows
    ]


def _reclassify_document(db: Session, document: Document, learned_rules: list[LearnedRule]) -> bool:
    """Recalcula el document_type de un documento usando las learned rules.

    Devuelve True si el tipo ha cambiado.
    """
    text = ""
    if document.pages:
        text = " ".join(page.text or "" for page in document.pages if page.text)
    if not text and document.source_path:
        text = document.source_path

    result = classify_document(
        filename=document.original_filename,
        source_path=document.source_path,
        text=text,
        learned_rules=learned_rules,
    )
    if result.document_type == document.document_type:
        return False

    document.document_type = result.document_type
    document.confidence = result.confidence
    document.processed_at = datetime.utcnow()
    return True


def process_approved_suggestions() -> dict:
    """Procesa sugerencias aprobadas: crea learned patterns, reclasifica docs, invalida cache, emite webhooks."""
    db = SessionLocal()
    try:
        # SELECT ... FOR UPDATE SKIP LOCKED evita que múltiples workers
        # procesen las mismas sugerencias simultáneamente (race condition).
        approved = list(
            db.scalars(
                select(ClassificationSuggestion)
                .where(ClassificationSuggestion.status == "approved")
                .order_by(ClassificationSuggestion.reviewed_at.asc().nulls_last())
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            ).all()
        )
        if not approved:
            return {
                "processed": 0,
                "patterns_created": 0,
                "reclassified": 0,
                "cache_invalidated": 0,
            }

        patterns_created = 0
        reclassified = 0
        directly_corrected_ids: set[int] = set()
        rule_affected_ids: set[int] = set()
        newly_active_patterns: list[LearnedPattern] = []

        for suggestion in approved:
            try:
                # classification_rule -> crear LearnedPattern
                if (
                    suggestion.suggestion_type == "classification_rule"
                    and suggestion.pattern_value
                    and suggestion.target_class
                ):
                    existing = db.scalar(
                        select(LearnedPattern).where(
                            LearnedPattern.pattern_type == "keyword",
                            LearnedPattern.pattern_value == suggestion.pattern_value,
                            LearnedPattern.target_action == "classify_as",
                        )
                    )
                    if existing:
                        existing.status = "active"
                        existing.confidence = max(existing.confidence, suggestion.confidence)
                        existing.source_suggestion_id = suggestion.id
                        existing.updated_at = datetime.utcnow()
                    else:
                        pattern = LearnedPattern(
                            pattern_type="keyword",
                            pattern_value=suggestion.pattern_value,
                            target_class=suggestion.target_class,
                            target_action="classify_as",
                            confidence=suggestion.confidence,
                            source_suggestion_id=suggestion.id,
                            status="active",
                        )
                        db.add(pattern)
                        db.flush()
                        newly_active_patterns.append(pattern)
                        patterns_created += 1
                    rule_affected_ids.add(suggestion.document_id)

                # classification_correction -> aplicar cambio directo al documento
                elif (
                    suggestion.suggestion_type == "classification_correction"
                    and suggestion.suggested_document_type
                ):
                    document = db.get(Document, suggestion.document_id)
                    if document and not document.deleted_at:
                        if document.document_type != suggestion.suggested_document_type:
                            document.document_type = suggestion.suggested_document_type
                            document.confidence = max(
                                suggestion.confidence, document.confidence or 0.0
                            )
                            document.processed_at = datetime.utcnow()
                            directly_corrected_ids.add(document.id)
                            reclassified += 1

                suggestion.status = "applied"
                suggestion.applied_at = datetime.utcnow()

            except Exception as exc:
                logger.exception(
                    "learning_loop_suggestion_failed suggestion_id=%s error=%s", suggestion.id, exc
                )
                continue

        all_affected_ids = directly_corrected_ids | rule_affected_ids

        # Recalcular clasificacion solo de docs afectados por nuevas reglas
        # (los docs con correccion directa ya tienen el tipo asignado por el admin)
        if newly_active_patterns:
            learned_rules = _load_active_learned_rules(db)
            for doc_id in rule_affected_ids:
                document = db.get(Document, doc_id)
                if document and not document.deleted_at:
                    try:
                        if _reclassify_document(db, document, learned_rules):
                            reclassified += 1
                    except Exception as exc:
                        logger.warning("reclassify_failed document_id=%s error=%s", doc_id, exc)

        db.commit()

        # Invalidar cache de IA solo si hubo cambios reales
        cache_invalidated = 0
        if reclassified > 0 or patterns_created > 0:
            try:
                # NOTE: invalidacion amplia porque las claves de cache no indexan
                # por documento. Futuro: invalidar selectivamente por budget_scope.
                cache_invalidated = invalidate_all_ai_cache()
            except Exception as exc:
                logger.warning("ai_cache_invalidation_failed error=%s", exc)

        # Emitir webhooks (in the same transaction as the business state change)
        for pattern in newly_active_patterns:
            try:
                emit_new_pattern_detected(
                    db,
                    pattern_id=pattern.id,
                    pattern_type=pattern.pattern_type,
                    pattern_value=pattern.pattern_value,
                    target_class=pattern.target_class,
                    target_action=pattern.target_action,
                    applied_count=pattern.applied_count,
                )
            except Exception as exc:
                logger.warning("webhook_new_pattern_failed pattern_id=%s error=%s", pattern.id, exc)

        # Webhook de baja confianza para docs reclasificados con confianza < umbral
        for doc_id in all_affected_ids:
            document = db.get(Document, doc_id)
            if (
                document
                and document.confidence is not None
                and document.confidence < LOW_CONFIDENCE_THRESHOLD
            ):
                try:
                    emit_classification_low_confidence(
                        db,
                        document_id=document.id,
                        filename=document.original_filename,
                        current_type=document.document_type,
                        confidence=document.confidence,
                        threshold=LOW_CONFIDENCE_THRESHOLD,
                        budget_scope_id=document.budget_scope_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "webhook_low_confidence_failed document_id=%s error=%s", doc_id, exc
                    )

        # Audit
        write_audit(
            db,
            user=None,
            action="learning_loop_processed",
            entity_type="classification_suggestion",
            entity_id=None,
            details={
                "processed": len(approved),
                "patterns_created": patterns_created,
                "reclassified": reclassified,
                "cache_invalidated": cache_invalidated,
            },
        )
        db.commit()

        return {
            "processed": len(approved),
            "patterns_created": patterns_created,
            "reclassified": reclassified,
            "cache_invalidated": cache_invalidated,
        }
    finally:
        db.close()


@celery_app.task(name="app.workers.learning_tasks.process_approved_suggestions_task")
def process_approved_suggestions_task() -> dict:
    return process_approved_suggestions()


@celery_app.task(name="app.workers.learning_tasks.reclassify_document_task")
def reclassify_document_task(document_id: int) -> dict:
    """Reclasifica un documento concreto usando las learned rules activas."""
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if not document or document.deleted_at:
            return {"reclassified": False, "reason": "not_found"}
        learned_rules = _load_active_learned_rules(db)
        changed = _reclassify_document(db, document, learned_rules)
        db.commit()
        if (
            changed
            and document.confidence is not None
            and document.confidence < LOW_CONFIDENCE_THRESHOLD
        ):
            emit_classification_low_confidence(
                db,
                document_id=document.id,
                filename=document.original_filename,
                current_type=document.document_type,
                confidence=document.confidence,
                threshold=LOW_CONFIDENCE_THRESHOLD,
                budget_scope_id=document.budget_scope_id,
            )
        return {
            "reclassified": changed,
            "document_id": document_id,
            "new_type": document.document_type,
        }
    finally:
        db.close()
