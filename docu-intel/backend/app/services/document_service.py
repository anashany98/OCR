from __future__ import annotations

from app.core.config import settings
from app.ocr.factory import get_ocr_engine, get_ocr_engine_class
from app.parsers.router import parse_document

from app.services.business_extraction import persist_business_extraction
from app.services.document_registration_service import register_upload, register_existing_file
from app.services.document_reprocess_service import reprocess_document, reprocess_document_page, soft_delete_document
from app.services.document_processing_core import (
    _emit_document_webhooks,
    _process_full_parse,
    process_document,
    processing_mode_from_job_type,
    reprocess_page_number_from_job_type,
    mode_requires_file_parse,
    sanitize_text_for_database,
)
from app.services.document_embedding_pipeline import prepare_document_chunks, embed_many_with_metadata
from app.services.embeddings import embed_many, should_create_embeddings
from app.services.file_security import inspect_file_for_ingestion
from app.services.plan_extraction import persist_plan_extraction
from app.services.quality import evaluate_document_quality, update_document_quality
from app.services.webhooks import emit_integration_webhook

# OCR engine factory re-exports. Tests monkey-patch
# ``document_service.get_ocr_engine_class`` with a lambda that returns a
# fake engine class so the cascade / single-engine wiring can be exercised
# without instantiating Tesseract or PaddleOCR.
__all__ = [
    "get_ocr_engine",
    "get_ocr_engine_class",
]
