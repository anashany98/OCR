from __future__ import annotations

# Public facade for the document-processing helpers. The
# original module (before F4b's refactor split the helpers
# into ``document_processing_core`` /
# ``document_reprocess_service`` /
# ``document_embedding_pipeline``) implemented every step
# here; we keep the imports so callers that
# ``from app.services import document_service`` continue to
# get the public surface they were written against.
#
# These imports are intentional re-exports, not dead code.
# ``__all__`` below enumerates every name this module
# re-exports so linters, ``import *`` callers and ``dir()``
# can see them.
from app.core.config import settings  # noqa: F401
from app.ocr.factory import get_ocr_engine, get_ocr_engine_class  # noqa: F401
from app.parsers.router import parse_document  # noqa: F401
from app.services.business_extraction import persist_business_extraction  # noqa: F401
from app.services.document_registration_service import (  # noqa: F401
    register_existing_file,
    register_upload,
)
from app.services.document_reprocess_service import (  # noqa: F401
    reprocess_document,
    reprocess_document_page,
    soft_delete_document,
)
from app.services.document_processing_core import (  # noqa: F401
    _emit_document_webhooks,
    _process_full_parse,
    mode_requires_file_parse,
    process_document,
    processing_mode_from_job_type,
    reprocess_page_number_from_job_type,
    sanitize_text_for_database,
)
from app.services.document_embedding_pipeline import (  # noqa: F401
    embed_many_with_metadata,
    prepare_document_chunks,
)
from app.services.embeddings import embed_many, should_create_embeddings  # noqa: F401
from app.services.file_security import inspect_file_for_ingestion  # noqa: F401
from app.services.plan_extraction import persist_plan_extraction  # noqa: F401
from app.services.quality import evaluate_document_quality, update_document_quality  # noqa: F401
from app.services.webhooks import emit_integration_webhook  # noqa: F401

# OCR engine factory re-exports. Tests monkey-patch
# ``document_service.get_ocr_engine_class`` with a lambda that returns a
# fake engine class so the cascade / single-engine wiring can be exercised
# without instantiating Tesseract or PaddleOCR.
__all__ = [
    "_emit_document_webhooks",
    "_process_full_parse",
    "embed_many",
    "embed_many_with_metadata",
    "emit_integration_webhook",
    "evaluate_document_quality",
    "get_ocr_engine",
    "get_ocr_engine_class",
    "inspect_file_for_ingestion",
    "mode_requires_file_parse",
    "parse_document",
    "persist_business_extraction",
    "persist_plan_extraction",
    "prepare_document_chunks",
    "process_document",
    "processing_mode_from_job_type",
    "register_existing_file",
    "register_upload",
    "reprocess_document",
    "reprocess_document_page",
    "reprocess_page_number_from_job_type",
    "sanitize_text_for_database",
    "settings",
    "should_create_embeddings",
    "soft_delete_document",
    "update_document_quality",
]
