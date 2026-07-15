from __future__ import annotations

from app.models import DocumentPage
from app.ocr.base import OCRResult
from app.services.document_processing_core import _should_select_ocr_candidate
from app.services.ocr_decision import decide_ocr_result
from app.services.ocr_page_roles import (
    infer_ocr_content_kind,
    is_probably_decorative_embedded_media,
)


def test_embedded_short_logo_is_decorative_but_embedded_receipt_is_not():
    assert is_probably_decorative_embedded_media(
        image_path="ab/hash_pages/embedded/image001.jpg",
        text="[Imagen incrustada: image001.jpg] Decoraciones Egea",
    )
    assert not is_probably_decorative_embedded_media(
        image_path="ab/hash_pages/embedded/receipt.jpg",
        text="[Imagen incrustada: receipt.jpg] Factura 2025-13 total 128,40 EUR",
    )


def test_native_parser_output_never_becomes_an_ocr_page():
    assert infer_ocr_content_kind(
        current_kind=None,
        ocr_engine="pymupdf",
        image_path=None,
        text="Factura digital legible",
    ) == "native_text"


def test_reprocess_never_replaces_a_better_selected_ocr_result():
    page = DocumentPage(
        document_id=1,
        page_number=1,
        text="Pedido proveedor 250213 con total 1200 euros",
        ocr_confidence=0.95,
        ocr_calibrated_confidence=0.794,
        ocr_content_kind="ocr",
    )
    candidate = OCRResult(
        text="Pedido proveedor",
        confidence=0.50,
        blocks=[],
        engine="vision",
    )

    assert not _should_select_ocr_candidate(page, candidate, decide_ocr_result(candidate))
