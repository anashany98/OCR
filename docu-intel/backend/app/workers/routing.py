from __future__ import annotations

from app.models import Document

HEAVY_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
FAST_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".eml", ".xls", ".xlsx", ".xlsm"}
# Document types that need the OCR-heavy / GPU queue. Alongside ``plano`` and
# the generic ``imagen``, the new image subtypes (fotos de producto, muestras
# de tela, croquis) are scanned photos that benefit from the GPU cascade, so
# they are routed to ``ocr_heavy`` by type too — not only by extension.
HEAVY_TYPES = {"plano", "imagen", "foto_producto", "muestra_tela", "croquis_medida"}


def queue_for_document(document: Document, job_type: str) -> str:
    if job_type.endswith(":embeddings") or job_type == "embeddings":
        return "embeddings"
    extension = (document.extension or "").lower()
    document_type = (document.document_type or "").lower()
    if document_type in HEAVY_TYPES or extension in HEAVY_EXTENSIONS:
        return "ocr_heavy"
    if extension in FAST_EXTENSIONS:
        return "text_fast"
    return "text_fast"
