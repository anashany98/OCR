from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.ocr.paddle import PaddleOCREngine
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def _table_to_markdown(table: list[list]) -> str:
    """Render a 2D table (as returned by pdfplumber/Camelot) as a clean
    markdown table. Empty cells stay empty so the column count is
    preserved. A row is skipped only if every cell is empty/None."""
    if not table:
        return ""
    # Filter rows that are completely empty.
    rows: list[list[str]] = []
    for r in table:
        cleaned = [
            "" if c is None else str(c).replace("\n", " ").replace("|", "\\|").strip()
            for c in r
        ]
        if any(c for c in cleaned):
            rows.append(cleaned)
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    if ncols < 2:
        return ""  # single column is not a table, just lines
    # Pad rows.
    rows = [r + [""] * (ncols - len(r)) for r in rows]

    def esc(cell: str) -> str:
        return cell.strip() or " "

    # The first row becomes the header. If it's mostly empty (e.g. the
    # table is body-only with a blank header line), synthesise one.
    header = rows[0]
    if sum(1 for c in header if c) < max(1, ncols // 2):
        header = [f"col{i+1}" for i in range(ncols)]
        body = rows
    else:
        header = rows[0]
        body = rows[1:]

    lines = [
        "| " + " | ".join(esc(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)


def _extract_table_markdown(path: Path, page_index: int) -> str:
    """Try pdfplumber's table extractor on a single page with multiple
    strategies and pick the best result. Returns a markdown block
    (possibly empty) suitable to append after the page text. Failures
    are swallowed; the rest of the page text still flows through.

    Why multiple strategies: pdfplumber's default is conservative and
    often splits multi-column layouts (issuer / client address blocks,
    or item description / quantity / unit-price / total) into a single
    table with many empty cells. We try three strategies, score them
    by row density and column count, and keep the one that looks most
    like a real table.
    """
    try:
        import pdfplumber
    except Exception:
        return ""
    strategies = [
        # default: pdfplumber decides per page
        {},
        # text/text: better for layouts with no visible lines
        {"vertical_strategy": "text", "horizontal_strategy": "text",
         "snap_tolerance": 4, "join_tolerance": 3},
        # text/lines: line-based row detection, text-based column
        {"vertical_strategy": "text", "horizontal_strategy": "lines",
         "snap_tolerance": 4, "join_tolerance": 3},
    ]
    best_md = ""
    best_score = -1.0
    try:
        with pdfplumber.open(path) as pdf:
            if page_index >= len(pdf.pages):
                return ""
            page = pdf.pages[page_index]
            for opts in strategies:
                try:
                    tables = page.extract_tables(opts) or []
                except Exception:
                    continue
                if not tables:
                    continue
                # Score: sum of non-empty cells in the table minus
                # penalty for tables that are mostly empty (multi-col
                # side-by-side blocks that pdfplumber wrongly merges).
                for t in tables:
                    if len(t) < 2 or not t[0]:
                        continue
                    rows = t
                    ncols = max((len(r) for r in rows), default=0)
                    if ncols < 2:
                        continue
                    nonempty = sum(
                        1 for r in rows for c in r
                        if c is not None and str(c).strip()
                    )
                    total_cells = sum(len(r) for r in rows)
                    density = nonempty / total_cells if total_cells else 0
                    # Heavily penalise low density (the address-block
                    # case returns 4-col tables with ~25% density).
                    score = nonempty * density
                    md = _table_to_markdown(rows)
                    if score > best_score and md:
                        best_score = score
                        best_md = md
            if best_md:
                return "\n\n--- Tablas detectadas ---\n\n" + best_md
    except Exception:
        return ""
    return ""


async def _maybe_vision_table(path: Path, page_index: int, output_dir: Path) -> str:
    """If the vision LLM is configured and the page produced no
    structured text (i.e. it's scanned/photographed), ask the vision
    model to transcribe the table as markdown. Returns empty string on
    any failure (vision is best-effort)."""
    if not settings.vision_table_transcription:
        return ""
    if not settings.vision_base_url or not settings.vision_model:
        return ""
    try:
        from app.ai.local_client import LocalVisionClient
        client = LocalVisionClient()
        return await client.transcribe_table_from_pdf_page(
            path, page_index, output_dir=output_dir
        )
    except Exception:
        return ""


def parse_pdf(path: Path, output_dir: Path, ocr_engine: PaddleOCREngine) -> ExtractedDocument:
    import fitz

    # Fast path: if PDF is fully digital text, skip OCR but still render the
    # page to an image so the document viewer has a preview to show.
    if is_digital_pdf(path):
        pages: list[ExtractedPage] = []
        output_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(path) as pdf:
            if len(pdf) > settings.max_pdf_pages:
                raise ValueError(f"max_pdf_pages exceeded: {len(pdf)} > {settings.max_pdf_pages}")
            for index, page in enumerate(pdf, start=1):
                text = page.get_text("text").strip()
                rect = page.rect
                # Append any tables detected by pdfplumber as markdown
                # so the LLM can keep column structure.
                table_md = _extract_table_markdown(path, index - 1)
                if table_md:
                    text = f"{text}\n{table_md}" if text else table_md.lstrip()
                # Render page to a preview PNG (~2x zoom). Cheap and gives the
                # viewer something to show without re-running OCR.
                image_file = output_dir / f"page_{index}.png"
                page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False).save(image_file)
                pages.append(
                    ExtractedPage(
                        page_number=index,
                        width=float(rect.width),
                        height=float(rect.height),
                        text=text,
                        image_path=str(image_file),
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
                table_md = _extract_table_markdown(path, index - 1)
                if table_md:
                    text = f"{text}\n{table_md}"
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
                # If PaddleOCR returned nothing useful, try the vision LLM
                # as a recovery path for tables (best-effort).
                if not text and settings.vision_table_transcription and settings.vision_model:
                    import asyncio
                    try:
                        loop = asyncio.new_event_loop()
                        try:
                            vision_md = loop.run_until_complete(
                                _maybe_vision_table(path, index - 1, output_dir)
                            )
                        finally:
                            loop.close()
                        if vision_md:
                            text = vision_md
                            ocr_confidence = max(ocr_confidence or 0.0, 0.85)
                            blocks = [
                                ExtractedBlock(
                                    block_type="table",
                                    text=vision_md,
                                    page_number=index,
                                    bbox=(0.0, 0.0, float(rect.width), float(rect.height)),
                                    confidence=0.85,
                                    source_engine="vision",
                                )
                            ]
                            page_engine = "vision"
                    except Exception:
                        pass
                # If PaddleOCR returned nothing, keep the engine label as
                # ``empty`` so the admin can spot pages that came in blank
                # despite being routed to OCR.
                page_engine = page_engine or ("paddleocr" if text else "empty")

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
