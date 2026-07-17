from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.content_router import classify_content
from app.parsers.doc import parse_doc
from app.parsers.docx import parse_docx
from app.parsers.dwg import parse_dwg
from app.parsers.dxf import parse_dxf
from app.parsers.excel import parse_excel
from app.parsers.image import parse_image
from app.parsers.msg import parse_msg
from app.parsers.pdf import parse_pdf
from app.parsers.pdf_docling import parse_pdf_docling
from app.parsers.plain import parse_plain_text
from app.parsers.types import ExtractedDocument
from app.services.docling_client import DoclingClient, DoclingError, DoclingNotEligible
from app.services.metrics.ocr import track_docling_fallback

logger = logging.getLogger("app.parsers.router")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".eml"}
MSG_EXTENSIONS = {".msg"}
DXF_EXTENSIONS = {".dxf"}
DWG_EXTENSIONS = {".dwg"}


class UnsupportedDocumentFormatError(ValueError):
    """Raised when a file has no safe text-extraction route.

    Reading arbitrary binary data as UTF-8 with ``errors=ignore`` can create
    corrupted pseudo-text that contaminates chunks and retrieval.  This error
    lets the pipeline expose a manual-review/convert action instead.
    """


def _unsupported_format(path: Path) -> UnsupportedDocumentFormatError:
    extension = path.suffix.lower() or "(sin extensión)"
    return UnsupportedDocumentFormatError(
        f"Formato no compatible para extracción segura: {extension}. "
        "Convierte el archivo a PDF, DXF o a un formato de documento compatible."
    )


def _parse_pdf(
    path: Path,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    folder_hint: str | None,
) -> ExtractedDocument:
    """PDF dispatch with opt-in Docling route + graceful fallback.

    Order of checks (the cheap ones first):

    1. ``settings.pdf_parser`` — if it is not ``"docling"`` the
       legacy parser is used directly. The default is ``"legacy"``
       so a deployment that has not opted in sees no behaviour
       change.
    2. :meth:`DoclingClient.is_configured` — the master switch
       (``DOCLING_ENABLED``) AND a non-empty endpoint must both
       be true. A typo that only flips one of them routes to
       legacy instead of failing every PDF.
    3. :func:`parse_pdf_docling` is called. On any
       :class:`DoclingError` the router logs a warning, records
       a metric so the operator can see the degradation in
       ``/metrics``, and falls back to :func:`parse_pdf` so the
       document is still ingested.

    The legacy path is the same :func:`parse_pdf` the router
    has always called — the contract is unchanged for every
    non-Docling caller.
    """
    if settings.pdf_parser != "docling" or not DoclingClient.is_configured():
        if settings.pdf_parser == "docling" and not DoclingClient.is_configured():
            # Operator asked for Docling but the service is not
            # configured. Count it so the silent misconfiguration
            # is visible.
            track_docling_fallback("not_configured")
            logger.warning(
                "PDF_PARSER=docling but Docling is not configured; "
                "falling back to the legacy PDF parser"
            )
        return parse_pdf(path, output_dir, ocr_engine, folder_hint=folder_hint)

    try:
        return parse_pdf_docling(
            path, output_dir, ocr_engine, folder_hint=folder_hint
        )
    except DoclingNotEligible as exc:
        # Normal control-flow signal: the file is not a PDF, the
        # service is disabled, or the configuration is missing.
        # The router does not need to fall back; we just log and
        # call the legacy parser so the caller never sees a
        # Docling-specific exception.
        track_docling_fallback("not_eligible")
        logger.info(
            "Docling not eligible for %s (%s); using legacy PDF parser",
            path.name,
            exc,
        )
        return parse_pdf(path, output_dir, ocr_engine, folder_hint=folder_hint)
    except DoclingError as exc:
        # Recoverable failure: the service answered with an
        # error, the circuit breaker is open, or the response
        # exceeded the byte cap. The document is still
        # ingestable through the legacy parser.
        track_docling_fallback("failure")
        logger.warning(
            "Docling failed for %s (%s); falling back to the legacy PDF parser",
            path.name,
            exc,
        )
        return parse_pdf(path, output_dir, ocr_engine, folder_hint=folder_hint)
    except Exception as exc:  # noqa: BLE001 — last-resort safety net
        # The parser should never raise an unhandled exception,
        # but if it does we still want the document to land in
        # the legacy path. The metric bucket is the bounded
        # ``"exception"`` value, not a free-form string, so the
        # label cardinality cannot explode.
        track_docling_fallback("exception")
        logger.exception(
            "Unexpected Docling failure for %s: %s: %s — falling back to legacy",
            path.name,
            type(exc).__name__,
            exc,
        )
        return parse_pdf(path, output_dir, ocr_engine, folder_hint=folder_hint)


def parse_document(
    path: Path,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    folder_hint: str | None = None,
) -> ExtractedDocument:
    extension = path.suffix.lower()

    # Content-aware routing for images: classify before OCR
    if extension in IMAGE_EXTENSIONS:
        classification = classify_content(path, folder_hint=folder_hint)
        content_route = classification.route.value if classification.route else None
        logger.info(
            "Content router: %s -> %s (confidence=%.2f, reason=%s)",
            path.name,
            classification.route.value,
            classification.confidence,
            classification.reason,
        )
        return parse_image(path, output_dir, ocr_engine, content_route=content_route)

    if extension == ".pdf":
        return _parse_pdf(path, output_dir, ocr_engine, folder_hint)
    if extension in EXCEL_EXTENSIONS:
        return parse_excel(path, output_dir=output_dir, ocr_engine=ocr_engine)
    if extension == ".docx":
        return parse_docx(path, output_dir=output_dir, ocr_engine=ocr_engine)
    if extension == ".doc":
        return parse_doc(path, output_dir=output_dir, ocr_engine=ocr_engine)
    if extension in MSG_EXTENSIONS:
        return parse_msg(path, output_dir=output_dir, ocr_engine=ocr_engine)
    if extension in DXF_EXTENSIONS:
        return parse_dxf(path, output_dir)
    if extension in DWG_EXTENSIONS:
        return parse_dwg(path, output_dir)
    if extension in TEXT_EXTENSIONS:
        return parse_plain_text(path)
    raise _unsupported_format(path)
