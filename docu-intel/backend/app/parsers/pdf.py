from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage
from app.services.metrics import (
    track_ocr_dpi_escalation,
    track_ocr_language_detected,
    track_ocr_tier_used,
    track_parser_fallback_failure,
)
from app.services.ocr_language import (
    LanguageProfile,
    paddle_lang_for,
    tesseract_lang_for,
)

logger = logging.getLogger("app.parsers.pdf")


def _render_page_to_image(page, image_file: Path, *, dpi: int) -> str | None:
    """Render a PDF page and atomically leave the bytes on disk
    at ``image_file`` with the correct extension for the
    encoded format (``.jpg`` or ``.png``).

    The caller passes a path with a placeholder suffix (e.g.
    ``page_1_dpi300.tmp``); the helper replaces the suffix
    with the actual format and returns the new extension so
    the caller can update its own ``Path`` reference. The
    on-disk name and the payload always agree, so the
    browser infers the right Content-Type (audit OPS-01:
    the old version always wrote to ``.png`` regardless of
    format, which made some browsers refuse previews and
    proxies cache them under the wrong MIME).

    Why JPEG over PNG for OCR pre-processing:
    - A 300 DPI A1 page as PNG is ~50 MB. As JPEG quality 85 it
      is ~5 MB. PaddleOCR still reads the same characters —
      text recognition is unaffected by the lossy compression
      at quality >= 80.
    - 10x less disk I/O when writing the temp image.
    - 10x less VRAM when PaddleOCR loads the image.
    - 30-40% faster OCR end-to-end on large pages.

    Returns ``None`` when both encoders fail; the DPI ladder
    will try a lower DPI on the next iteration.
    """
    import fitz

    # The two encoders have different APIs: JPEG goes through
    # ``tobytes()`` + ``Path.write_bytes()`` and PNG goes
    # through ``Pixmap.save()``. We try JPEG first (much
    # smaller on disk, identical OCR accuracy) and fall back
    # to PNG when the encoder crashes (rare) or the JPEG
    # write fails (e.g. disk full). Both ``encode`` and
    # ``write`` for JPEG are inside the same ``try`` so a
    # write failure also triggers the PNG fallback.
    target_ext: str | None = None
    payload: tuple[str, object] | None = None

    try:
        zoom = max(0.5, float(dpi) / 72.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        jpeg_bytes = pix.tobytes("jpeg", jpg_quality=85)
        # OPS-1: write the JPEG bytes to a sibling file with a
        # ``.jpg.staging`` suffix and let the trailing rename
        # step below move them onto the final path. Both the
        # encode and the write are inside this ``try`` so
        # either failure triggers the PNG fallback.
        staging_jpg = image_file.with_suffix(".jpg.staging")
        staging_jpg.write_bytes(jpeg_bytes)
        target_ext = ".jpg"
        payload = ("staging", staging_jpg)
    except PermissionError as exc:
        # CR9: Permission denied when writing page image. This is a
        # technical failure, not an OCR quality issue. Track the metric
        # so operators can see permission problems in /metrics.
        from app.services.metrics.ocr import track_ocr_render_permission_failure

        track_ocr_render_permission_failure()
        logger.error(
            "Permission denied rendering page at dpi=%d: %s",
            dpi,
            exc,
        )
        return None
    except Exception as exc:
        # OPS-1 / OPS-2: the JPEG encoder in PyMuPDF raises on
        # a handful of pages (weird CMYK profiles, broken
        # embedded streams), and a write failure here can
        # also fire if the disk is full. We fall back to PNG
        # so the rest of the pipeline still works, but we
        # used to do it silently — the operator had no way
        # to know that the fallback was firing on every
        # page of a given document. Log + counter so the
        # JPEG/PNG MIME mismatch that ships with the .png
        # extension (audit OPS-01) becomes visible.
        logger.debug(
            "page render to JPEG failed for dpi=%d: %s: %s — falling back to PNG",
            dpi,
            type(exc).__name__,
            exc,
        )
        track_parser_fallback_failure(stage="pdf_render_jpeg", kind="exception")
        try:
            zoom = max(0.5, float(dpi) / 72.0)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            target_ext = ".png"
            payload = ("pixmap", pix)
        except Exception as exc:
            # Both renderers failed: the page cannot be
            # rasterized at this DPI. The DPI ladder will try
            # a lower DPI next. Log and counter so a corrupt
            # PDF shows up in /metrics instead of as a silent
            # blank page downstream.
            logger.warning(
                "page render failed for dpi=%d (both JPEG and PNG): %s: %s",
                dpi,
                type(exc).__name__,
                exc,
            )
            track_parser_fallback_failure(stage="pdf_render_png", kind="exception")
            return None

    if payload is None or target_ext is None:
        return None
    kind, blob = payload

    # Move the encoded bytes to the final on-disk path with
    # the right extension. The bytes already live in a
    # staging file when we got here through the JPEG
    # branch (``payload[1]`` is the staging ``Path``); in
    # the PNG branch ``payload[1]`` is a ``Pixmap`` that
    # ``save()`` writes itself, with the format inferred
    # from the suffix.
    final_path = image_file.with_suffix(target_ext)
    try:
        if kind == "staging":
            staging = blob  # type: ignore[assignment]
            if final_path.exists():
                final_path.unlink()
            staging.rename(final_path)
        else:
            pix = blob  # type: ignore[assignment]
            # ``Pixmap.save()`` infers the format from the
            # suffix, so we just point it at the final path.
            pix.save(str(final_path))
    except PermissionError as exc:
        from app.services.metrics.ocr import track_ocr_render_permission_failure

        track_ocr_render_permission_failure()
        logger.error(
            "Permission denied finalising page render at dpi=%d: %s",
            dpi,
            exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "page render finalise failed at dpi=%d (target=%s): %s: %s",
            dpi,
            target_ext,
            type(exc).__name__,
            exc,
        )
        track_parser_fallback_failure(stage="pdf_render_finalise", kind="exception")
        return None
    return target_ext


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
            "" if c is None else str(c).replace("\n", " ").replace("|", "\\|").strip() for c in r
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
        header = [f"col{i + 1}" for i in range(ncols)]
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


_T = TypeVar("_T")


def _run_coro_sync(coro: Awaitable[_T]) -> _T:
    """Run an awaitable from a synchronous call site.

    The vision-table fallback used to call
    ``asyncio.new_event_loop()`` from inside a sync function. That
    pattern leaks the loop (no ``asyncio.run`` cleanup) and breaks
    when the caller is already inside a running event loop (Celery
    workers, FastAPI request handlers). This helper:

    * uses :func:`asyncio.run` when no event loop is running
      (the Celery worker case), or
    * off-loads the coroutine to a fresh daemon thread with its
      own loop and joins the result, when a loop *is* already
      running on this thread (the FastAPI request case).

    Failures bubble up unchanged; the caller is expected to
    swallow them in a best-effort fallback.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is None:
        return asyncio.run(coro)
    # A loop is already running on this thread (FastAPI / async
    # test). Spin up a worker thread, run the coroutine in its
    # own loop, and block until it finishes.
    import threading

    result: list[_T] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


# O1 — DPI ladder: when Tier 1 returns very little text on a
# scanned page, the characters are probably too small for the
# current DPI. We re-render at progressively higher DPI and
# re-run the cascade, up to 3 attempts.  The 600 DPI level is
# only tried when the previous two levels produced completely
# empty text (not just low quality) to avoid wasting time on
# pages that are readable at 400 DPI but below the quality bar.
_DPI_MIN_TEXT_LENGTH = 30
_DPI_MIN_CONFIDENCE = 0.55  # DPI-escalación umbral (relajado vs low_ocr=0.70)


def _get_dpi_ladder(page_width: float = 0, page_height: float = 0) -> list[int]:
    """Build the DPI ladder dynamically from the configured base DPI.

    The final +300 step is reserved for pages whose lower-DPI attempts are
    empty; the caller stops before it for merely low-quality OCR.
    For small pages (width < 400pt), start 100 DPI higher so the
    rendered image is large enough for OCR.
    """
    base = settings.pdf_ocr_dpi
    min_side = min(page_width, page_height) if page_width and page_height else 999
    # Small page: start 100 DPI higher
    if min_side < 400:
        base = min(base + 100, 400)
    return [base, base + 100, base + 300]


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

    DPI escalation is capped: 600 DPI is only attempted when both
    300 and 400 produced completely empty text (0 chars), not just
    low quality. This avoids spending 2-3 extra OCR rounds on pages
    that are readable at 400 DPI but below the quality bar.
    """
    from app.ocr.base import OCRResult

    best_image: Path | None = None
    best_ocr: OCRResult | None = None
    best_engine: str = ""
    prev_dpi = 0
    prev_text_empty = True

    for dpi in _get_dpi_ladder(page.rect.width, page.rect.height):
        # Skip 600 DPI unless previous attempts returned no text at all.
        if dpi == 600 and not prev_text_empty:
            break

        image_file = output_dir / f"page_{page_number}_dpi{dpi}.tmp"
        rendered_ext = _render_page_to_image(page, image_file, dpi=dpi)
        if rendered_ext is None:
            continue
        image_file = image_file.with_suffix(rendered_ext)

        try:
            ocr = ocr_engine.extract(image_file)
        except Exception as exc:
            logger.debug(
                "OCR engine %s crashed on page %d dpi %d: %s: %s",
                getattr(ocr_engine, "name", "?"),
                page_number,
                dpi,
                type(exc).__name__,
                exc,
            )
            track_parser_fallback_failure(stage="pdf_ocr_extract", kind="exception")
            continue

        actual_engine = getattr(ocr, "engine", None) or ocr_engine.name
        text = (ocr.text or "").strip()
        conf = ocr.confidence if ocr.confidence is not None else 0.0

        if best_image is None or _ocr_is_usable(text, conf):
            best_image, best_ocr, best_engine = image_file, ocr, actual_engine

        if prev_dpi > 0 and dpi > prev_dpi:
            track_ocr_dpi_escalation(from_dpi=prev_dpi, to_dpi=dpi)
        prev_dpi = dpi
        prev_text_empty = len(text) == 0

        if _ocr_is_usable(text, conf):
            break

    # Fallback: render at the base DPI as the page preview image
    # so the viewer always has something to show.
    if best_image is None:
        base_dpi = _get_dpi_ladder()[0]
        image_file = output_dir / f"page_{page_number}.tmp"
        rendered_ext = _render_page_to_image(page, image_file, dpi=base_dpi)
        if rendered_ext is not None:
            image_file = image_file.with_suffix(rendered_ext)
            best_image = image_file
        else:
            # Both renderers failed even at the base DPI: the page
            # stays blank. The viewer will show a "no preview"
            # placeholder rather than a corrupt image.
            best_image = None
        best_ocr = OCRResult(text="", confidence=0.0, blocks=[], engine="")
        best_engine = ""

    # Rename the best image to the canonical name so the viewer
    # can find it without knowing the DPI. OPS-1: the canonical
    # extension follows the actual format on disk — we use
    # ``.jpg`` when the page was rendered as JPEG, ``.png``
    # when the renderer fell back. The viewer looks up the
    # canonical path from ``DocumentPage.image_path`` so it
    # always sees the right extension.
    if best_image is not None:
        canonical_ext = best_image.suffix or ".png"
        canonical = output_dir / f"page_{page_number}{canonical_ext}"
    else:
        canonical = output_dir / f"page_{page_number}.png"
    if best_image is not None and best_image != canonical:
        try:
            if canonical.exists():
                canonical.unlink()
            best_image.rename(canonical)
            best_image = canonical
        except Exception as exc:
            # OPS-2: filesystem rename can fail on Windows
            # (target locked, permission denied, different
            # volume). The non-canonical filename is still
            # usable downstream, but the viewer won't find the
            # preview unless it also looks up the per-DPI
            # filename. Count so a sudden spike here becomes
            # visible.
            logger.debug(
                "could not rename %s → %s: %s: %s",
                best_image,
                canonical,
                type(exc).__name__,
                exc,
            )
            track_parser_fallback_failure(stage="pdf_rename_canonical", kind="exception")

    return best_image, best_ocr, best_engine


def _ocr_is_usable(text: str, confidence: float) -> bool:
    """A page result is usable when it has enough text and the
    confidence is above the DPI-ladder floor. This is a lower
    bar than the cascade's ``_is_acceptable`` — the DPI ladder
    is about "did the re-render help at all?" not "is this
    production-quality text?"."""
    return len(text.strip()) >= _DPI_MIN_TEXT_LENGTH and confidence >= _DPI_MIN_CONFIDENCE


def _ocr_scanned_page_by_index(
    pdf_path: Path,
    page_index_0: int,
    output_dir: Path,
    ocr_engine,
) -> tuple[Path | None, object, str]:
    """Thread-safe variant of ``_ocr_with_dpi_ladder``.

    Instead of taking a live ``fitz.Page`` object (which is not safe to
    share across threads), this opens its own ``fitz.open(pdf_path)``,
    fetches the page by 0-based index, and runs the same DPI ladder +
    canonical-rename logic. PyMuPDF supports multiple concurrent
    readers on the same path, so each worker thread calling this is
    isolated.

    Returns ``(image_file, ocr_result, engine_name)`` — same contract
    as ``_ocr_with_dpi_ladder``.
    """
    import fitz

    page_number = page_index_0 + 1
    with fitz.open(pdf_path) as pdf:
        page = pdf[page_index_0]
        return _ocr_with_dpi_ladder(page, output_dir, page_number, ocr_engine)


def _process_scanned_page(
    pdf_path: Path,
    page_index_0: int,
    output_dir: Path,
    ocr_engine,
    language: str | None,
    rect_wh: tuple[float, float],
    content_route: str,
) -> ExtractedPage:
    """Process one scanned PDF page, end to end. Thread-safe.

    Opens its own fitz handle, runs the DPI-ladder OCR cascade, applies
    the vision-table fallback when configured, and returns a complete
    :class:`ExtractedPage`. Designed to run inside a worker thread so
    the pages of a multi-page document are OCR'd in parallel.
    """
    import time as _time

    from app.parsers.types import ExtractedBlock

    # Set the per-page language on the cascade (thread-local attribute).
    with contextlib.suppress(Exception):
        ocr_engine.current_language = language
    # FASE 5: set content_route so the cascade can skip unnecessary tiers.
    with contextlib.suppress(Exception):
        ocr_engine.current_content_route = content_route
    with contextlib.suppress(Exception):
        ocr_engine.current_page_number = page_index_0 + 1

    rect_w, rect_h = rect_wh
    page_number = page_index_0 + 1
    started = _time.perf_counter()

    image_file, ocr, actual_engine = _ocr_scanned_page_by_index(
        pdf_path, page_index_0, output_dir, ocr_engine
    )
    image_path = str(image_file) if image_file is not None else None
    text = ocr.text or ""
    ocr_confidence = ocr.confidence
    blocks = [
        ExtractedBlock(
            block_type=block.block_type or "text",
            text=block.text,
            page_number=page_number,
            bbox=block.bbox,
            confidence=block.confidence,
            source_engine=actual_engine,
        )
        for block in ocr.blocks
    ]
    page_engine = actual_engine if text else "empty"

    # Vision-table recovery path (best-effort) when the OCR cascade
    # returned nothing usable. Runs in the same worker thread.
    if not text and settings.vision_table_transcription and settings.vision_model:
        try:
            vision_md = _run_coro_sync(
                _maybe_vision_table(pdf_path, page_index_0, output_dir, content_route=content_route)
            )
            if vision_md:
                text = vision_md
                ocr_confidence = max(ocr_confidence or 0.0, 0.85)
                blocks = [
                    ExtractedBlock(
                        block_type="table",
                        text=vision_md,
                        page_number=page_number,
                        bbox=(0.0, 0.0, rect_w, rect_h),
                        confidence=0.85,
                        source_engine="vision",
                    )
                ]
                page_engine = "vision"
        except Exception as exc:
            logger.warning(
                "pdf vision-table fallback failed for %s page %d: %s: %s",
                pdf_path,
                page_number,
                type(exc).__name__,
                exc,
            )
            track_parser_fallback_failure(stage="pdf_vision_table", kind="exception")

    elapsed_ms = int((_time.perf_counter() - started) * 1000)
    page = ExtractedPage(
        page_number=page_number,
        width=rect_w,
        height=rect_h,
        text=text,
        image_path=image_path,
        ocr_confidence=ocr_confidence,
        ocr_content_kind=ocr.content_kind or "ocr",
        ocr_engine=page_engine,
        ocr_engine_version=ocr.engine_version,
        ocr_warnings=list(ocr.warnings),
        blocks=blocks,
    )
    # Stash the per-page timing so the caller can persist it. The
    # ExtractedPage dataclass doesn't carry this field; we attach it as
    # an attribute that the persistence layer reads opportunistically.
    page.processing_time_ms = elapsed_ms  # type: ignore[attr-defined]
    return page


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
    except Exception as exc:
        # OPS-2: pdfplumber is an optional dependency; if it's
        # missing we fall back to OCR-only output. This branch
        # runs at most once per worker (the import is cached),
        # so we log it once with a clear marker and bump the
        # counter so the operator can see the deployment is
        # missing the package.
        logger.warning(
            "pdfplumber import failed at %s: %s: %s — table extraction disabled",
            path,
            type(exc).__name__,
            exc,
        )
        track_parser_fallback_failure(stage="pdfplumber_table", kind="import_error")
        return ""
    strategies = [
        # default: pdfplumber decides per page
        {},
        # text/text: better for layouts with no visible lines
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 4,
            "join_tolerance": 3,
        },
        # text/lines: line-based row detection, text-based column
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "lines",
            "snap_tolerance": 4,
            "join_tolerance": 3,
        },
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
                except Exception as exc:
                    # OPS-2: pdfplumber raises on weird layouts
                    # (multi-column invoices with overlapping
                    # text). We try the next strategy, but we
                    # also log + count so a sustained spike of
                    # these shows up on /metrics.
                    logger.debug(
                        "pdfplumber.extract_tables strategy failed at %s page %d: %s: %s",
                        path,
                        page_index,
                        type(exc).__name__,
                        exc,
                    )
                    track_parser_fallback_failure(stage="pdfplumber_table", kind="exception")
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
                    nonempty = sum(1 for r in rows for c in r if c is not None and str(c).strip())
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
    except Exception as exc:
        # OPS-2: outer safety net for unexpected pdfplumber
        # crashes (corrupt PDF, permission errors, etc.). Log
        # and bump the counter so a PDF that consistently
        # blows up here becomes visible in /metrics.
        logger.warning(
            "pdfplumber table extraction crashed at %s page %d: %s: %s",
            path,
            page_index,
            type(exc).__name__,
            exc,
        )
        track_parser_fallback_failure(stage="pdfplumber_table", kind="exception")
        return ""
    return ""


async def _maybe_vision_table(
    path: Path,
    page_index: int,
    output_dir: Path,
    content_route: str | None = None,
) -> str:
    """If the vision LLM is configured and the page produced no
    structured text (i.e. it's scanned/photographed), ask the vision
    model to transcribe the content. Handles tables, handwritten text,
    and scanned documents. Returns empty string on any failure.
    """
    if not settings.vision_table_transcription:
        return ""
    if not settings.vision_base_url or not settings.vision_model:
        return ""
    try:
        from app.ai.local_client import LocalVisionClient
        from app.parsers.image import _get_vision_prompt

        client = LocalVisionClient()
        prompt = _get_vision_prompt(content_route)
        text = await client.transcribe_table_from_pdf_page(path, page_index, output_dir=output_dir)
        if text and len(text.strip()) > 20:
            return text
        # Fallback: content-aware prompt for the specific page
        return await client.describe(
            path,
            prompt=prompt,
            max_tokens=2000,
        )
    except Exception as exc:
        logger.warning(
            "vision-table async call failed for %s page %d: %s: %s",
            path,
            page_index,
            type(exc).__name__,
            exc,
        )
        track_parser_fallback_failure(stage="pdf_vision_table", kind="exception")
        return ""


def parse_pdf(
    path: Path,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    folder_hint: str | None = None,
) -> ExtractedDocument:
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

    # Content-aware routing: classify the PDF before processing.
    # This runs a quick text scan on the first 3 pages to detect
    # if it's a plan, interior design content, etc.
    from app.parsers.content_router import classify_content

    content_classification = classify_content(path, folder_hint=folder_hint)
    content_route = content_classification.route.value
    if content_classification.route.value != "standard_ocr":
        logger.info(
            "PDF content router: %s -> %s (confidence=%.2f, reason=%s)",
            path.name,
            content_classification.route.value,
            content_classification.confidence,
            content_classification.reason,
        )

    pages: list[ExtractedPage | None] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    # Ensure the directory is writable by the current user (fixes root-owned dirs)
    import os as _os

    try:
        _os.chmod(str(output_dir), 0o755)
        _os.chmod(str(output_dir.parent), 0o755)
    except OSError:
        pass
    file_size_mb = path.stat().st_size / (1024 * 1024)
    with fitz.open(path) as pdf:
        page_count = len(pdf)
        if page_count > settings.max_pdf_pages:
            raise ValueError(f"max_pdf_pages exceeded: {page_count} > {settings.max_pdf_pages}")
        if file_size_mb > 100:
            logger.info(
                "Processing large PDF: %s (%.1f MB, %d pages)",
                path.name,
                file_size_mb,
                page_count,
            )
        # Pre-size the pages list so results land in page order regardless
        # of which worker thread finishes first.
        pages = [None] * page_count
        # Pages that need the OCR cascade (scanned) are collected here and
        # processed in parallel; digital pages are handled inline below.
        scanned_indices: list[int] = []

        # O2 — track the language we detected from the first *digital*
        # page so a scan-only page that comes later still gets the
        # right language pack (scans do not have any embedded text to
        # sniff). We also pass this profile to the cascade's
        # ``current_language`` attribute so the per-language thresholds
        # apply.
        document_language: str | None = None

        # ---- Phase 1 (single thread): digital pages + language sniff ----
        # PyMuPDF is not thread-safe across pages of the same document, so
        # all fitz access happens here, sequentially, before any OCR.
        for index_0, page in enumerate(pdf):
            index = index_0 + 1
            text = page.get_text("text").strip()
            rect = page.rect

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
                    paddle_lang=paddle_lang_for(document_language, default=settings.paddle_lang),
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
            with contextlib.suppress(Exception):  # pragma: no cover - defensive
                track_ocr_tier_used(
                    ocr_engine.name,
                    document_type=_guess_document_type_for_metrics(path),
                )

            # --- Digital fast path: embedded text is enough ----------
            if len(text) >= 30:
                table_md = _extract_table_markdown(path, index - 1)
                if table_md:
                    text = f"{text}\n{table_md}" if text else table_md.lstrip()
                blocks = [
                    ExtractedBlock(
                        block_type="text",
                        text=text,
                        page_number=index,
                        bbox=(0.0, 0.0, float(rect.width), float(rect.height)),
                        confidence=1.0,
                        source_engine="pymupdf",
                    )
                ]
                # P1.2: Skip the low-res preview render for digital pages.
                # The viewer generates thumbnails on demand via the
                # /thumbnails API endpoint. This saves CPU time on
                # large digital PDFs that don't need OCR.
                pages[index_0] = ExtractedPage(
                    page_number=index,
                    width=float(rect.width),
                    height=float(rect.height),
                    text=text,
                    image_path=None,
                    # Native PDF text has not gone through probabilistic OCR:
                    # its extraction confidence is therefore deterministic.
                    # Keeping this at 1.0 also lets downstream review logic
                    # distinguish a healthy digital page from an unscored one.
                    ocr_confidence=1.0,
                    ocr_content_kind="native_text",
                    ocr_engine="pymupdf",
                    blocks=blocks,
                )
            else:
                # Scanned page: defer to Phase 2 (parallel OCR). We only
                # record its index + geometry now; the OCR cascade runs
                # in a worker thread that opens its own fitz handle.
                scanned_indices.append(index_0)

    # ---- Phase 2 (parallel): OCR cascade for scanned pages ----
    # Each scanned page opens its own ``fitz.open(path)`` (PyMuPDF allows
    # concurrent readers) and runs the full cascade independently. The
    # thread-local preprocess/OSD caches and the cascade's thread-local
    # ``current_language`` keep pages isolated. The OCR engines release
    # the GIL in their C extensions, so real parallelism is achieved.
    if scanned_indices:
        # Resolve geometry for each scanned page from a fresh fitz handle
        # (cheap: just rect lookup, no render).
        page_rects: dict[int, tuple[float, float]] = {}
        with fitz.open(path) as pdf:
            for idx in scanned_indices:
                rect = pdf[idx].rect
                page_rects[idx] = (float(rect.width), float(rect.height))

        max_workers = min(len(scanned_indices), settings.ocr_page_parallelism)

        def _ocr_page(index_0: int) -> tuple[int, ExtractedPage]:
            page = _process_scanned_page(
                pdf_path=path,
                page_index_0=index_0,
                output_dir=output_dir,
                ocr_engine=ocr_engine,
                language=document_language,
                rect_wh=page_rects[index_0],
                content_route=content_route,
            )
            return index_0, page

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pdf-ocr") as executor:
            for index_0, page in executor.map(_ocr_page, scanned_indices):
                pages[index_0] = page

    # Drop any slots that remained None (e.g. scanned page processing failed
    # and returned nothing). Filter defensively so the caller always gets a
    # contiguous list.
    final_pages = [p for p in pages if p is not None]
    return ExtractedDocument(pages=final_pages)


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
    if (
        "plano" in name
        or "escritorio" in name
        or "medici" in name
        or "bancada" in name
        or "dtm" in name
    ):
        return "plano"
    if "factura" in name:
        return "factura"
    return "otro"
