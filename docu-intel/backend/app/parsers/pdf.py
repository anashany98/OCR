from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.ocr.paddle import PaddleOCREngine
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def parse_pdf(path: Path, output_dir: Path, ocr_engine: PaddleOCREngine) -> ExtractedDocument:
    import fitz

    # Fast path: if PDF is fully digital text, skip OCR
    if is_digital_pdf(path):
        pages: list[ExtractedPage] = []
        with fitz.open(path) as pdf:
            if len(pdf) > settings.max_pdf_pages:
                raise ValueError(f"max_pdf_pages exceeded: {len(pdf)} > {settings.max_pdf_pages}")
            for index, page in enumerate(pdf, start=1):
                text = page.get_text("text").strip()
                rect = page.rect
                table_text = _extract_table_text(path, index - 1)
                if table_text:
                    text = f"{text}\n\n{table_text}"
                pages.append(
                    ExtractedPage(
                        page_number=index,
                        width=float(rect.width),
                        height=float(rect.height),
                        text=text,
                        image_path=None,
                        ocr_confidence=1.0,
                        # Per-page engine tag. We use a single helper so the
                        # OCR/no-OCR decision and the engine label stay in sync.
                        ocr_engine="pymupdf",
                        blocks=[
                            ExtractedBlock(
                                block_type="text",
                                text=text,
                                page_number=index,
                                bbox=(0.0, 0.0, float(rect.width), float(rect.height)),
                                confidence=1.0,
                                source_engine="pymupdf",
                            )
                        ],
                    )
                )
        return ExtractedDocument(pages=pages)

    # Original OCR path for scanned/image PDFs
    pages: list[ExtractedPage] = []
    with fitz.open(path) as pdf:
        if len(pdf) > settings.max_pdf_pages:
            raise ValueError(f"max_pdf_pages exceeded: {len(pdf)} > {settings.max_pdf_pages}")
        for index, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            rect = page.rect
            blocks: list[ExtractedBlock] = []
            image_path: str | None = None
            ocr_confidence: float | None = None
            page_engine: str = "empty"

            if text:
                table_text = _extract_table_text(path, index - 1)
                if table_text:
                    text = f"{text}\n\n{table_text}"
                blocks.append(
                    ExtractedBlock(
                        block_type="text",
                        text=text,
                        page_number=index,
                        bbox=(0.0, 0.0, float(rect.width), float(rect.height)),
                        confidence=1.0,
                        source_engine="pymupdf",
                    )
                )
                page_engine = "pymupdf"

            if len(text) < 30:
                output_dir.mkdir(parents=True, exist_ok=True)
                image_file = output_dir / f"page_{index}.png"
                zoom = max(0.5, float(settings.pdf_ocr_dpi) / 72.0)
                page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(image_file)
                image_path = str(image_file)
                ocr = ocr_engine.extract(image_file)
                text = ocr.text or text
                ocr_confidence = ocr.confidence
                blocks = [
                    ExtractedBlock(
                        block_type="text",
                        text=block.text,
                        page_number=index,
                        bbox=block.bbox,
                        confidence=block.confidence,
                        source_engine="paddleocr",
                    )
                    for block in ocr.blocks
                ]
                # If PaddleOCR returned nothing, keep the engine label as
                # ``empty`` so the admin can spot pages that came in blank
                # despite being routed to OCR.
                page_engine = "paddleocr" if text else "empty"

            pages.append(
                ExtractedPage(
                    page_number=index,
                    width=float(rect.width),
                    height=float(rect.height),
                    text=text,
                    image_path=image_path,
                    ocr_confidence=ocr_confidence,
                    ocr_engine=page_engine,
                    blocks=blocks,
                )
            )
    return ExtractedDocument(pages=pages)


def is_digital_pdf(path: Path) -> bool:
    """Check if PDF has sufficient digital text content (>90% text pages)."""
    import fitz

    with fitz.open(path) as pdf:
        text_pages = 0
        total_pages = len(pdf)
        for page in pdf:
            text = page.get_text("text").strip()
            if len(text) >= 30:
                text_pages += 1
        return text_pages / total_pages > 0.9 if total_pages > 0 else False


def _extract_table_text(path: Path, page_index: int) -> str:
    try:
        import pdfplumber

        lines: list[str] = []
        with pdfplumber.open(path) as pdf:
            if page_index >= len(pdf.pages):
                return ""
            for table in pdf.pages[page_index].extract_tables() or []:
                for row in table:
                    values = [str(cell).strip() for cell in row if cell and str(cell).strip()]
                    if values:
                        lines.append(" | ".join(values))
        return "\n".join(lines)
    except Exception:
        return ""
