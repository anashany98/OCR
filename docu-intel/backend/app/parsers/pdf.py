from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage
from app.services.metrics import track_ocr_dpi_escalation, track_ocr_language_detected, track_ocr_tier_used
from app.services.ocr_language import (
    LanguageProfile,
    paddle_lang_for,
    tesseract_lang_for,
)


def _render_page_to_jpeg(page, image_file: Path, *, dpi: int) -> bool:
    """Render a PDF page to a JPEG file instead of PNG.

    Why JPEG over PNG for OCR pre-processing:
    - A 300 DPI A1 page as PNG is ~50 MB. As JPEG quality 85 it is ~5 MB.
      PaddleOCR still reads the same characters — text recognition is
      unaffected by the lossy compression at quality >= 80.
    - 10x less disk I/O when writing the temp image.
    - 10x less VRAM when PaddleOCR loads the image.
    - 30-40% faster OCR end-to-end on large pages.

    Returns True on success, False on any failure (caller falls back
    to PNG). Failures are swallowed because OCR is best-effort.
    """
    import fitz

    try:
        zoom = max(0.5, float(dpi) / 72.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        # ``tobytes`` with jpg_quality returns a JPEG-encoded buffer
        # (PyMuPDF honours the quality arg on JPEG output).
        jpeg_bytes = pix.tobytes("jpeg", jpg_quality=85)
        image_file.write_bytes(jpeg_bytes)
        return True
    except Exception:
        # Fall back to PNG so the rest of the pipeline still works.
        try:
            zoom = max(0.5, float(dpi) / 72.0)
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(image_file)
            return True
        except Exception:
            return False


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


# O1 — DPI ladder: when Tier 1 returns very little text on a
# scanned page, the characters are probably too small for the
# current DPI. We re-render at progressively higher DPI and
# re-run the cascade, up to 3 attempts.
_DPI_LADDER: list[int] = [300, 400, 600]
_DPI_MIN_TEXT_LENGTH = 30
_DPI_MIN_CONFIDENCE = 0.40


def _ocr_with_dpi_ladder(
    page,
    output_dir: Path,
    page_number: int,
    ocr_engine,
) -> tuple[Path, object, str]:
    """Render a scanned PDF page at progressively higher DPI until
    the cascade produces a usable result.

    Returns ``(image_file, ocr_result, engine_name)``. The image
    file is the *highest* DPI render we tried (the one whose OCR
    result we kept). The function is fail-safe: on any exception
    we return the result of the *last successful* attempt.
    """
    from app.ocr.base import OCRResult

    best_image: Path | None = None
    best_ocr: OCRResult | None = None
    best_engine: str = ""
    prev_dpi = 0

    for dpi in _DPI_LADDER:
        image_file = output_dir / f"page_{page_number}_dpi{dpi}.png"
        if not _render_page_to_jpeg(page, image_file, dpi=dpi):
            continue

        try:
            ocr = ocr_engine.extract(image_file)
        except Exception:
            continue

        actual_engine = getattr(ocr, "engine", None) or ocr_engine.name
        text = (ocr.text or "").strip()
        conf = ocr.confidence if ocr.confidence is not None else 0.0

        if best_image is None:
            best_image, best_ocr, best_engine = image_file, ocr, actual_engine
        elif _ocr_is_usable(text, conf):
            best_image, best_ocr, best_engine = image_file, ocr, actual_engine

        if prev_dpi > 0 and dpi > prev_dpi:
            track_ocr_dpi_escalation(from_dpi=prev_dpi, to_dpi=dpi)
        prev_dpi = dpi

        if _ocr_is_usable(text, conf):
            break

    # Fallback: render at the base DPI as the page preview image
    # so the viewer always has something to show.
    if best_image is None:
        base_dpi = _DPI_LADDER[0]
        image_file = output_dir / f"page_{page_number}.png"
        _render_page_to_jpeg(page, image_file, dpi=base_dpi)
        best_image = image_file
        best_ocr = OCRResult(text="", confidence=0.0, blocks=[], engine="")
        best_engine = ""

    # Rename the best image to the canonical name so the viewer
    # can find it without knowing the DPI.
    canonical = output_dir / f"page_{page_number}.png"
    if best_image != canonical:
        try:
            if canonical.exists():
                canonical.unlink()
            best_image.rename(canonical)
            best_image = canonical
        except Exception:
            pass

    return best_image, best_ocr, best_engine


def _ocr_is_usable(text: str, confidence: float) -> bool:
    """A page result is usable when it has enough text and the
    confidence is above the DPI-ladder floor. This is a lower
    bar than the cascade's ``_is_acceptable`` — the DPI ladder
    is about "did the re-render help at all?" not "is this
    production-quality text?"."""
    return len(text.strip()) >= _DPI_MIN_TEXT_LENGTH and confidence >= _DPI_MIN_CONFIDENCE


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


def parse_pdf(path: Path, output_dir: Path, ocr_engine: BaseOCREngine) -> ExtractedDocument:
    """Extract text from a PDF, per-page.

    Decision is made **per page**, not per document:

    - **Digital page** (>= 30 chars of embedded text): use ``page.get_text()``
      directly. No image rendering, no OCR. ~10-50 ms per page.
    - **Scanned page** (< 30 chars): render to image, run OCR cascade
      (Tesseract -> PaddleOCR). ~2-10 s per page.
    - **Vision fallback**: if a scanned page yields no text, ask the
      vision LLM to transcribe tables. Best-effort.

    This replaces the old all-or-nothing ``is_digital_pdf`` check that
    would route a 100-page document with 90 digital + 10 scanned pages
    entirely through OCR.
    """
    import fitz

    pages: list[ExtractedPage] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    file_size_mb = path.stat().st_size / (1024 * 1024)
    with fitz.open(path) as pdf:
        page_count = len(pdf)
        if page_count > settings.max_pdf_pages:
            raise ValueError(f"max_pdf_pages exceeded: {page_count} > {settings.max_pdf_pages}")
        if file_size_mb > 100:
            logger.info(
                "Processing large PDF: %s (%.1f MB, %d pages)",
                path.name, file_size_mb, page_count,
            )
        # O2 — track the language we detected from the first *digital*
        # page so a scan-only page that comes later still gets the
        # right language pack (scans do not have any embedded text to
        # sniff). We also pass this profile to the cascade's
        # ``current_language`` attribute so the per-language
        # thresholds apply.
        document_language: str | None = None
        for index, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            rect = page.rect
            blocks: list[ExtractedBlock] = []
            image_path: str | None = None
            ocr_confidence: float | None = None
            # Empty string = "no engine picked yet". Using "" (falsy) so the
            # ``or`` fallback below correctly promotes the OCR result's engine
            # label when this page is scanned. Initialising to "empty"
            # (a truthy string) would make the ``or`` always short-circuit.
            page_engine: str = ""

            # O2 — per-page language detection. We sniff the embedded
            # text on every page; for scans we fall back to the
            # document-level language we cached from the first
            # digital page. The profile is recorded both as a
            # Prometheus counter and on the cascade so the
            # per-language thresholds apply.
            page_profile = LanguageProfile.for_text(
                text,
                default_tesseract_lang=settings.tesseract_lang,
                default_paddle_lang=settings.paddle_lang,
            )
            if page_profile.detected:
                document_language = page_profile.detected
            effective_profile = page_profile
            if not page_profile.detected and document_language:
                effective_profile = LanguageProfile(
                    detected=document_language,
                    thresholds=page_profile.thresholds,
                    tesseract_lang=tesseract_lang_for(
                        document_language, default=settings.tesseract_lang
                    ),
                    paddle_lang=paddle_lang_for(
                        document_language, default=settings.paddle_lang
                    ),
                )
            track_ocr_language_detected(
                effective_profile.detected or "unknown",
                _guess_document_type_for_metrics(path),
            )
            # S0.2 — emit a tier-by-document-type counter on the
            # cascade. We register the per-page cascade winner
            # here; the cascading engine's own ``_record_winner``
            # already emits the tier-only counter, this call
            # additionally labels the tier with the document
            # type so the admin UI can see which document types
            # lean on which tier.
            try:
                track_ocr_tier_used(
                    ocr_engine.name,
                    document_type=_guess_document_type_for_metrics(path),
                )
            except Exception:  # pragma: no cover - defensive
                pass

            # Tell the cascade the current page's language so the
            # per-language thresholds apply. We use ``getattr`` /
            # ``setattr`` instead of a direct attribute access
            # because ``BaseOCREngine`` is a ``Protocol`` and the
            # cascade-specific ``current_language`` is not part of
            # the interface contract. Non-cascading engines (single
            # Tesseract, single PaddleOCR) will simply ignore the
            # attribute set.
            try:
                setattr(ocr_engine, "current_language", effective_profile.detected)
            except Exception:  # pragma: no cover - defensive
                pass

            # --- Digital fast path: embedded text is enough ----------
            if len(text) >= 30:
                table_md = _extract_table_markdown(path, index - 1)
                if table_md:
                    text = f"{text}\n{table_md}" if text else table_md.lstrip()
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
                # Render a low-res preview so the document viewer has
                # something to show, but skip the high-res render the
                # OCR path would do.
                image_file = output_dir / f"page_{index}.png"
                _render_page_to_jpeg(page, image_file, dpi=144)
                image_path = str(image_file)
                # Digital extraction has perfect confidence: the text
                # is straight from the PDF's content stream, not guessed.
                ocr_confidence = 1.0
                page_engine = "pymupdf"
            else:
                # --- Scanned / image page: OCR cascade + O1 DPI ladder
                image_file, ocr, actual_engine = _ocr_with_dpi_ladder(
                    page, output_dir, index, ocr_engine,
                )
                image_path = str(image_file)
                text = ocr.text or text
                ocr_confidence = ocr.confidence
                blocks = [
                    ExtractedBlock(
                        block_type="text",
                        text=block.text,
                        page_number=index,
                        bbox=block.bbox,
                        confidence=block.confidence,
                        source_engine=actual_engine,
                    )
                    for block in ocr.blocks
                ]
                # If the cascade returned nothing useful, try the vision
                # LLM as a recovery path for tables (best-effort).
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
                # Keep the engine label accurate: if the cascade got
                # text, use the cascade's pick; if the page is still
                # empty, mark it as "empty" so the admin can spot the
                # pages that came in blank despite being routed to OCR.
                page_engine = page_engine or (actual_engine if text else "empty")

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
    """Check if PDF has sufficient digital text content (>90% text pages).

    Kept for backward compatibility with callers that want a quick
    yes/no answer. The per-page parser no longer uses this — it makes
    the digital/OCR decision per page.
    """
    import fitz

    with fitz.open(path) as pdf:
        text_pages = 0
        total_pages = len(pdf)
        for page in pdf:
            text = page.get_text("text").strip()
            if len(text) >= 30:
                text_pages += 1
        return text_pages / total_pages > 0.9 if total_pages > 0 else False


def _guess_document_type_for_metrics(path: Path) -> str:
    """Best-effort type guess for the Prometheus ``document_type`` label.

    The parser does not know the classified ``document_type`` at the
    time it runs (classification is a separate stage), so we look at
    the filename. This is used only as a *metric label* to break
    down the language distribution by document type; it does not
    affect the OCR logic.
    """
    name = path.name.lower()
    if "albaran" in name:
        return "albaran"
    if "presupuest" in name or "precio" in name or "hoja de confec" in name or "memoria" in name:
        return "presupuesto"
    if "pedido" in name or "pv" in name or "venta" in name:
        return "pedido"
    if "plano" in name or "escritorio" in name or "medici" in name or "bancada" in name or "dtm" in name:
        return "plano"
    if "factura" in name:
        return "factura"
    return "otro"
