"""Persisted, versioned image analysis used by the document pipeline."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, ImageAnalysis
from app.models.project import DocumentOccurrence

MODEL_NAME = "opencv-taxonomy"
MODEL_VERSION = "1"


def analyze_image_document(db: Session, document: Document, *, text: str = "") -> ImageAnalysis | None:
    """Upsert visual facts; repeated processing with identical bytes is a cache hit."""
    if not document.stored_filename:
        return None
    path = Path(document.stored_filename)
    from app.core.config import settings
    path = settings.files_dir / path
    if not path.is_file():
        return None
    # Do not load a high-resolution photograph into memory merely to make an
    # idempotence key.  The document hash is authoritative when available;
    # older rows fall back to a streaming digest.
    file_hash = document.file_hash or _sha256_file(path)
    existing = db.scalar(select(ImageAnalysis).where(ImageAnalysis.document_id == document.id))
    if existing and existing.perceptual_hash == file_hash and existing.model_name == MODEL_NAME and existing.model_version == MODEL_VERSION:
        return existing
    from app.parsers.clip_classifier import classify_image_multilabel
    result = classify_image_multilabel(path)
    occurrence = db.scalar(select(DocumentOccurrence).where(DocumentOccurrence.document_id == document.id).order_by(DocumentOccurrence.id))
    labels = [label for label, _ in result["labels"]]
    if existing is None:
        existing = ImageAnalysis(document_id=document.id, model_name=MODEL_NAME, model_version=MODEL_VERSION, confidence=0.0)
        db.add(existing)
    existing.occurrence_id = occurrence.id if occurrence else None
    existing.labels_json = labels
    # ``labels_json`` remains the compact legacy list consumed by search/UI.
    # Store confidence beside every label in a structured field so individual
    # visual facts stay auditable instead of inheriting one coarse score.
    existing.objects_json = [
        {"kind": "classification_label", "value": label, "confidence": float(confidence)}
        for label, confidence in result["labels"]
    ]
    existing.description = f"{result['primary_label']} ({result['primary_confidence']:.2f})"
    existing.visible_text = text or None
    existing.perceptual_hash = file_hash
    existing.confidence = float(result["primary_confidence"])
    existing.needs_review = result["primary_label"] == "desconocido"
    db.flush()
    return existing


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
