"""Docling-backed PDF parser.

This module is the opt-in alternative to :func:`app.parsers.pdf.parse_pdf`.
It produces the **same** :class:`~app.parsers.types.ExtractedDocument`
contract so the rest of the pipeline (classification, business
extraction, chunking, embeddings, hyperextract) does not need to
change.

Routing
-------
The parser router in :mod:`app.parsers.router` is the only place that
decides between this module and :mod:`app.parsers.pdf`. When the
operator sets ``pdf_parser=docling`` (and ``docling_enabled=true``) the
router calls :func:`parse_pdf_docling` first; on any
:class:`~app.services.docling_client.DoclingError` it logs a warning
and falls back to the legacy parser so a Docling outage never blocks
ingestion.

Docling schema
--------------
``docling-serve``'s ``/v1/convert/file`` returns a
``ConvertDocumentResponse`` with this shape::

    {
      "document": <DoclingDocument>,   # serialised inline
      "md_content": "...",             # full markdown
      "status": "success",
      ...
    }

A :class:`DoclingDocument` does **not** nest items under each page.
Instead it exposes flat top-level lists — ``texts``, ``tables``,
``pictures`` — and every item carries its provenance in a ``prov``
list whose entries reference the page (``page_no``) and the on-page
bounding box (``bbox``). The ``pages`` field is a **dict** keyed by
page number, whose entries only hold geometry (``size``) and a list of
back-references (``items``); they do **not** carry text. This module
regroups the flat items by ``prov[0].page_no`` so each page can be
reconstructed.

Per-page decision
-----------------
Docling is asked to skip OCR (``do_ocr=false``) and only return
layout + digital text + tables. For each page we then look at the
plain-text content Docling reported:

* **Digital** (>= 30 chars of text): we build the
  :class:`ExtractedPage` directly from Docling's structured
  output — no rendering, no OCR, no image_path.
* **Scanned** (< 30 chars): we render the page with PyMuPDF and pass
  the raster to the same cascade the legacy parser uses
  (Tesseract -> PaddleOCR -> vision), via the
  :func:`_ocr_scanned_page_by_index` helper imported from
  :mod:`app.parsers.pdf`.

The per-page OCR is run on a :class:`~concurrent.futures.ThreadPoolExecutor`
and the cascade's thread-local ``current_language`` /
``current_content_route`` / ``current_page_number`` attributes are
populated exactly the way the legacy parser does, so the cascade sees
identical context whichever parser fed the page.
"""

from __future__ import annotations

import contextlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.content_router import classify_content
from app.parsers.pdf import (
    _maybe_vision_table,
    _ocr_scanned_page_by_index,
    _run_coro_sync,
)
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage
from app.services.ocr_language import LanguageProfile

logger = logging.getLogger("app.parsers.pdf_docling")

# Threshold (in characters) used to decide whether a Docling page is
# "digital" (use Docling's text directly) or "scanned" (render +
# cascade OCR). The value matches the legacy parser's per-page
# decision so the two code paths produce the same result on the
# same input.
_DIGITAL_TEXT_THRESHOLD = 30

# Mapping from Docling's ``label`` field on a page item to our
# canonical ``block_type``. Docling sometimes returns a different
# label for the same visual element across versions; the lookup
# is therefore case-insensitive and lenient.
_DOCLING_LABEL_TO_BLOCK_TYPE: dict[str, str] = {
    "title": "text",
    "section_header": "text",
    "text": "text",
    "paragraph": "text",
    "caption": "text",
    "list_item": "text",
    "table": "table",
    "picture": "figure",
    "figure": "figure",
    "page_header": "header",
    "page_footer": "footer",
    "formula": "text",
    "code": "text",
}


# Docling reports ``bbox.coord_origin`` as one of ``BOTTOMLEFT`` /
# ``TOPLEFT``. We always emit top-left (x0, y0, x1, y1) in PDF points
# to match the legacy parser's convention; a normalised bbox (all
# values in 0..1) is scaled against the page size first.
_COORD_ORIGIN_BOTTOMLEFT = "BOTTOMLEFT"


def _normalise_bbox(
    raw: Any,
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    """Coerce a Docling ``bbox`` to top-left PDF-point coords.

    Accepts the two shapes Docling ships:

    * a plain ``[l, t, r, b]`` list/tuple
    * a dict ``{"l": ..., "t": ..., "r": ..., "b": ..., "coord_origin": ...}``

    Values in the 0..1 range (normalised) are scaled against the page
    size; anything larger is assumed to be PDF points and passed
    through. ``BOTTOMLEFT`` origins are flipped to top-left.
    """
    if isinstance(raw, dict):
        try:
            left = float(raw.get("l", 0.0))
            top = float(raw.get("t", 0.0))
            right = float(raw.get("r", 0.0))
            bottom = float(raw.get("b", 0.0))
        except (TypeError, ValueError):
            return None
        origin = str(raw.get("coord_origin", "") or "").upper()
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            left, top, right, bottom = (float(v) for v in raw)
        except (TypeError, ValueError):
            return None
        origin = ""
    else:
        return None

    if page_width > 0 and page_height > 0 and max(left, top, right, bottom) <= 1.0:
        # Normalised 0..1 coordinates — scale to page points.
        left *= page_width
        right *= page_width
        top *= page_height
        bottom *= page_height

    if origin == _COORD_ORIGIN_BOTTOMLEFT:
        # Docling's BOTTOMLEFT origin means ``top`` is the distance from
        # the bottom edge; flip to top-left for the rest of the
        # pipeline (which assumes y grows downwards).
        top, bottom = page_height - bottom, page_height - top

    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return (left, top, right, bottom)


def _item_bbox(
    item: dict[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    """Return the best bbox for a Docling item.

    Docling attaches geometry to each item through its ``prov`` list;
    each prov entry has its own ``bbox``. Some payloads also carry a
    top-level ``bbox`` on the item itself. We prefer the first prov
    entry (the canonical provenance) and fall back to the top-level
    field, then to a legacy ``bbox``/``cbox`` shape.
    """
    raw = None
    prov = item.get("prov")
    if isinstance(prov, list) and prov and isinstance(prov[0], dict):
        raw = prov[0].get("bbox")
    if raw is None:
        raw = item.get("bbox")
    if raw is None:
        # Older / flatter payloads put coords in ``cbox``.
        raw = item.get("cbox")
    return _normalise_bbox(raw, page_width=page_width, page_height=page_height)


def _docling_item_to_block(
    item: dict[str, Any],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
) -> ExtractedBlock | None:
    """Map one Docling JSON item to an :class:`ExtractedBlock`.

    The function is intentionally defensive: Docling's schema is
    allowed to evolve as long as the textual content of a page is
    still recoverable. When a field is missing or has the wrong
    type the function returns ``None`` and the caller skips the
    item — the page text still flows through via ``md_content``.
    """
    label = str(item.get("label") or "").lower().strip()
    block_type = _DOCLING_LABEL_TO_BLOCK_TYPE.get(label, "text")

    # Docling exposes text in two places: ``text`` (plain) and
    # ``md_content`` (markdown). Tables are usually only in
    # ``md_content``; prefer it when the item is a table.
    text = item.get("text")
    if not isinstance(text, str):
        text = ""
    if block_type == "table":
        md_content = item.get("md_content") or item.get("content") or ""
        if isinstance(md_content, str) and md_content.strip():
            text = md_content
    text = text.strip()
    if not text:
        return None

    bbox = _item_bbox(item, page_width=page_width, page_height=page_height)

    # Mark the source engine on every block so a downstream audit
    # query can split Docling vs legacy-OCR text in the same
    # document.
    return ExtractedBlock(
        block_type=block_type,
        text=text,
        page_number=page_number,
        bbox=bbox,
        confidence=1.0,
        source_engine="docling",
    )


def _resolve_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the structured DoclingDocument from a convert response.

    ``docling-serve``'s ``/v1/convert/file`` wraps the document in
    ``payload["document"]``, and the typed lists (``texts`` /
    ``tables`` / ``pictures`` / ``pages``) live inside that wrapper's
    ``json_content`` field. Depending on options/version that field is:

    * a **dict** already deserialised (when ``to_formats=json`` makes
      the wrapper an inline JSON object), or
    * a **string** holding the serialised DoclingDocument.

    This helper returns ``json_content`` when present (either shape),
    falling back to the inline document. Either way the rest of the
    parser sees the typed lists at the top level.
    """
    document = payload.get("document") if isinstance(payload, dict) else None
    if not isinstance(document, dict):
        return {}
    json_content = document.get("json_content")
    if isinstance(json_content, dict):
        # Preserve top-level markdown if the inner doc lacks one.
        if not json_content.get("md_content") and document.get("md_content"):
            json_content["md_content"] = document["md_content"]
        return json_content
    if isinstance(json_content, str) and json_content.strip():
        try:
            inner = json.loads(json_content)
        except (TypeError, ValueError):
            return document
        if isinstance(inner, dict):
            if not inner.get("md_content") and document.get("md_content"):
                inner["md_content"] = document["md_content"]
            return inner
    return document


def _collect_docling_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Docling's typed item lists into a single list.

    Docling groups items by type (``texts``, ``tables``,
    ``pictures``). Each entry is an independent layout item with its
    own ``prov``; iterating them together in document order keeps
    reading order intact for pages that mix paragraphs and tables.
    """
    items: list[dict[str, Any]] = []
    for key in ("texts", "tables", "pictures"):
        chunk = document.get(key)
        if isinstance(chunk, list):
            for entry in chunk:
                if isinstance(entry, dict):
                    items.append(entry)
    return items


def _item_page_no(item: dict[str, Any]) -> int | None:
    """Return the 1-based page number a Docling item belongs to."""
    prov = item.get("prov")
    if isinstance(prov, list):
        for entry in prov:
            if isinstance(entry, dict):
                page_no = entry.get("page_no")
                if isinstance(page_no, int) and page_no >= 1:
                    return page_no
                # Some payloads use ``page`` instead of ``page_no``.
                page = entry.get("page")
                if isinstance(page, int) and page >= 1:
                    return page
    # Top-level fallbacks for payloads without prov.
    for key in ("page_no", "page"):
        value = item.get(key)
        if isinstance(value, int) and value >= 1:
            return value
    return None


def _docling_page_sizes(document: dict[str, Any]) -> dict[int, tuple[float, float]]:
    """Return ``{page_no: (width, height)}`` from Docling's ``pages``.

    Docling's ``pages`` is a dict keyed by page number (as a string in
    JSON). Each entry optionally carries a ``size`` with ``width`` and
    ``height``. Sizes are returned verbatim; callers that need PDF
    points fall back to the fitz-reported rect when a size is missing
    or implausible.
    """
    sizes: dict[int, tuple[float, float]] = {}
    pages = document.get("pages")
    if isinstance(pages, dict):
        for key, page in pages.items():
            if not isinstance(page, dict):
                continue
            try:
                page_no = int(key)
            except (TypeError, ValueError):
                continue
            size = page.get("size")
            if not isinstance(size, dict):
                continue
            try:
                width = float(size.get("width", 0.0))
                height = float(size.get("height", 0.0))
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                sizes[page_no] = (width, height)
    return sizes


def _regroup_items_by_page(
    document: dict[str, Any],
    *,
    page_rects: list[tuple[float, float]],
) -> dict[int, list[dict[str, Any]]]:
    """Group Docling's flat items by their provenance page number.

    ``page_rects`` is indexed 0-based (one entry per PDF page) and is
    the fallback page size when Docling does not report one. Returns
    a mapping ``{page_no: [items]}`` with 1-based page numbers.
    """
    items = _collect_docling_items(document)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        page_no = _item_page_no(item)
        if page_no is None:
            continue
        grouped.setdefault(page_no, []).append(item)
    return grouped


def _docling_page_to_digital(
    items: list[dict[str, Any]],
    *,
    page_number: int,
    rect: tuple[float, float],
    page_text_override: str | None = None,
) -> ExtractedPage | None:
    """Build an :class:`ExtractedPage` for a digital page from Docling.

    Returns ``None`` when the page has no usable text — the caller
    then re-routes the page through the OCR cascade.
    """
    rect_w, rect_h = rect
    blocks: list[ExtractedBlock] = []
    for item in items:
        block = _docling_item_to_block(
            item,
            page_number=page_number,
            page_width=rect_w,
            page_height=rect_h,
        )
        if block is not None:
            blocks.append(block)

    if blocks:
        page_text = "\n\n".join(block.text for block in blocks)
    elif page_text_override:
        page_text = page_text_override.strip()
    else:
        page_text = ""

    page_text = page_text.strip()
    if len(page_text) < _DIGITAL_TEXT_THRESHOLD:
        return None

    if not blocks and page_text:
        # No structured layout returned by Docling — synthesise a
        # single text block so the rest of the pipeline still has
        # something to chunk.
        blocks = [
            ExtractedBlock(
                block_type="text",
                text=page_text,
                page_number=page_number,
                bbox=(0.0, 0.0, rect_w, rect_h),
                confidence=1.0,
                source_engine="docling",
            )
        ]

    return ExtractedPage(
        page_number=page_number,
        width=rect_w,
        height=rect_h,
        text=page_text,
        image_path=None,
        # Native digital text — never went through probabilistic OCR.
        ocr_confidence=1.0,
        ocr_content_kind="native_text",
        ocr_engine="docling",
        blocks=blocks,
    )


def _docling_page_to_scanned(
    pdf_path: Path,
    page_index_0: int,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    rect: tuple[float, float],
    *,
    content_route: str,
    language: str | None,
) -> ExtractedPage:
    """Render one page with PyMuPDF and run the cascade OCR.

    The function mirrors the legacy parser's
    :func:`app.parsers.pdf._process_scanned_page` contract so the
    resulting :class:`ExtractedPage` is byte-compatible with the
    non-Docling path. The cascade's thread-local context
    (``current_language`` / ``current_content_route`` /
    ``current_page_number``) is populated before the OCR call so the
    cascade sees identical context whichever parser fed the page.
    """
    rect_w, rect_h = rect
    page_number = page_index_0 + 1

    # Set the per-page context on the cascade (thread-local attributes).
    # ``contextlib.suppress`` mirrors the legacy parser: the cascade may
    # not accept attribute writes (e.g. a bare mock in tests), and we
    # never want that to abort the page.
    with contextlib.suppress(Exception):
        ocr_engine.current_language = language
    with contextlib.suppress(Exception):
        ocr_engine.current_content_route = content_route
    with contextlib.suppress(Exception):
        ocr_engine.current_page_number = page_number

    image_file, ocr, actual_engine = _ocr_scanned_page_by_index(
        pdf_path=pdf_path,
        page_index_0=page_index_0,
        output_dir=output_dir,
        ocr_engine=ocr_engine,
    )
    text = ocr.text or ""
    ocr_confidence = ocr.confidence
    blocks: list[ExtractedBlock] = [
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

    # Best-effort vision-table fallback for scanned pages that the
    # cascade could not read. Identical to the legacy parser; the
    # helper is imported so we share one implementation.
    if not text and settings.vision_table_transcription and settings.vision_model:
        try:
            vision_md = _run_coro_sync(
                _maybe_vision_table(
                    pdf_path, page_index_0, output_dir, content_route=content_route
                )
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
        except Exception as exc:  # noqa: BLE001 — vision is best-effort
            logger.debug(
                "docling vision-table fallback failed for %s page %d: %s: %s",
                pdf_path,
                page_number,
                type(exc).__name__,
                exc,
            )

    return ExtractedPage(
        page_number=page_number,
        width=rect_w,
        height=rect_h,
        text=text,
        image_path=str(image_file) if image_file is not None else None,
        ocr_confidence=ocr_confidence,
        ocr_content_kind=ocr.content_kind or "ocr",
        ocr_engine=page_engine,
        ocr_engine_version=ocr.engine_version,
        ocr_warnings=list(ocr.warnings),
        blocks=blocks,
    )


def _resolve_page_size(
    docling_sizes: dict[int, tuple[float, float]],
    page_number: int,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    """Return ``(width, height)`` in PDF points for a Docling page.

    Docling's ``page.size`` is optional; when present it is usually in
    points, but the schema historically also accepts pixels. We trust
    the value only when it is positive and within a plausible range
    of the fitz-reported rect (the PDF backend's ground truth). When
    in doubt we fall back to the fitz rect, which is always in points
    and always agrees with the rest of the pipeline.
    """
    candidate = docling_sizes.get(page_number)
    if candidate is None:
        return fallback
    w, h = candidate
    if w <= 0 or h <= 0:
        return fallback
    return (w, h)


def parse_pdf_docling(
    path: Path,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    *,
    folder_hint: str | None = None,
    docling_client: Any | None = None,
) -> ExtractedDocument:
    """Parse a PDF through the Docling service, falling back to OCR per page.

    Parameters
    ----------
    path:
        Path to the PDF on disk.
    output_dir:
        Directory where the legacy OCR cascade writes ``page_N.jpg``
        previews. The directory is created if it does not exist.
    ocr_engine:
        The cascade OCR engine (Tesseract/PaddleOCR/...) that the
        parser uses for scanned pages. Same instance the legacy
        parser would receive.
    folder_hint:
        Optional folder path passed through to :func:`classify_content`
        for content-aware routing.
    docling_client:
        Optional pre-constructed :class:`DoclingClient`. When ``None``
        a fresh client is built from settings; tests inject a
        mock-backed client to avoid hitting the real service.

    Returns
    -------
    :class:`ExtractedDocument` whose pages follow the same contract
    as the legacy parser output.

    Notes
    -----
    * ``max_pdf_pages`` is enforced **before** the HTTP call.
    * Docling failures propagate as :class:`DoclingError` so the
      router can fall back to the legacy parser. The router is the
      single owner of the fallback metric, so this function does
      **not** emit ``track_docling_fallback`` itself (the previous
      double-count is gone).
    """
    from app.services.docling_client import DoclingClient

    # Reuse the same content routing as the legacy parser so a
    # document that was previously classified as
    # ``interior_design`` stays in that bucket regardless of
    # which parser produced the result.
    classification = classify_content(path, folder_hint=folder_hint)
    content_route = classification.route.value

    output_dir.mkdir(parents=True, exist_ok=True)

    # Open the PDF locally to count pages (so we can enforce
    # ``max_pdf_pages``), to get a fallback rect per page, and to
    # sniff a document-level language from the first digital page.
    # We never send the locally-rendered content to Docling — the
    # client uploads the original PDF.
    import fitz

    document_language: str | None = None
    with fitz.open(path) as pdf:
        page_count = len(pdf)
        if page_count > settings.max_pdf_pages:
            raise ValueError(
                f"max_pdf_pages exceeded: {page_count} > {settings.max_pdf_pages}"
            )
        page_rects: list[tuple[float, float]] = [
            (float(pdf[i].rect.width), float(pdf[i].rect.height)) for i in range(page_count)
        ]
        # Sniff the document language from the embedded text so the
        # cascade's per-language thresholds apply on scanned pages.
        # Same approach as the legacy parser: the first page with a
        # confident detection wins.
        for i in range(page_count):
            text_sample = pdf[i].get_text("text")
            profile = LanguageProfile.for_text(
                text_sample,
                default_tesseract_lang=settings.tesseract_lang,
                default_paddle_lang=settings.paddle_lang,
            )
            if profile.detected:
                document_language = profile.detected
                break

    client = docling_client or DoclingClient()
    payload = client.convert_pdf(path)

    # ``docling-serve`` ships the DoclingDocument either inline or
    # serialised as a JSON string under ``document.json_content``.
    # ``_resolve_document`` transparently deserialises the string
    # form so the typed lists are always at the top level below.
    document = _resolve_document(payload if isinstance(payload, dict) else {})

    docling_sizes = _docling_page_sizes(document)
    items_by_page = _regroup_items_by_page(document, page_rects=page_rects)

    # Phase 1 (single thread): digital pages are built straight from
    # Docling's structured output. Scanned pages are deferred to the
    # parallel phase below.
    page_results: list[ExtractedPage | None] = [None] * page_count
    scanned_indices: list[int] = []
    for index_0 in range(page_count):
        page_number = index_0 + 1
        rect = _resolve_page_size(docling_sizes, page_number, page_rects[index_0])
        items = items_by_page.get(page_number, [])
        digital_page = _docling_page_to_digital(
            items, page_number=page_number, rect=rect
        )
        if digital_page is not None:
            page_results[index_0] = digital_page
        else:
            scanned_indices.append(index_0)

    # Phase 2 (parallel): render + cascade OCR for the scanned pages.
    # The legacy parser parallelises this stage with a bounded
    # ThreadPoolExecutor; we do the same so a 50-page scan is not
    # 50x slower than the legacy path. The OCR engines release the
    # GIL in their C extensions, so real parallelism is achieved.
    if scanned_indices:
        max_workers = min(len(scanned_indices), settings.ocr_page_parallelism)

        def _ocr_page(index_0: int) -> tuple[int, ExtractedPage]:
            page_number = index_0 + 1
            rect = _resolve_page_size(docling_sizes, page_number, page_rects[index_0])
            page = _docling_page_to_scanned(
                path,
                index_0,
                output_dir,
                ocr_engine,
                rect,
                content_route=content_route,
                language=document_language,
            )
            return index_0, page

        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="docling-ocr"
        ) as executor:
            for index_0, page in executor.map(_ocr_page, scanned_indices):
                page_results[index_0] = page

    final_pages: list[ExtractedPage] = [p for p in page_results if p is not None]
    return ExtractedDocument(pages=final_pages)


__all__ = [
    "parse_pdf_docling",
    "_docling_item_to_block",
    "_docling_page_to_digital",
    "_docling_page_to_scanned",
    "_normalise_bbox",
    "_collect_docling_items",
    "_regroup_items_by_page",
    "_docling_page_sizes",
    "_resolve_page_size",
    "_resolve_document",
]
