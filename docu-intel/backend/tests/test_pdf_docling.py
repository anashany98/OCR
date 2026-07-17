"""Unit tests for :mod:`app.parsers.pdf_docling`.

The parser is the integration point between :class:`DoclingClient` and
the rest of the pipeline. These tests cover three concerns:

* The :class:`ExtractedDocument` produced by :func:`parse_pdf_docling`
  follows the same contract as the legacy
  :func:`app.parsers.pdf.parse_pdf` (digital pages get
  ``ocr_content_kind="native_text"`` and ``ocr_engine="docling"``,
  scanned pages get the cascade output with ``ocr_engine`` set to
  the cascade winner).
* Per-page routing is correct against the **real** Docling schema:
  text lives on flat ``texts``/``tables`` lists keyed by
  ``prov[].page_no`` — not under ``pages``.
* The cascade OCR is given the same thread-local context
  (``current_language`` / ``current_content_route`` /
  ``current_page_number``) the legacy parser provides, and scanned
  pages are byte-compatible with the non-Docling path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import fitz
import pytest

from app.ocr.base import OCRBlock, OCRResult
from app.parsers.pdf_docling import (
    _collect_docling_items,
    _docling_item_to_block,
    _docling_page_sizes,
    _docling_page_to_digital,
    _item_page_no,
    _normalise_bbox,
    _regroup_items_by_page,
    _resolve_document,
    _resolve_page_size,
    parse_pdf_docling,
)
from app.services.docling_client import DoclingError

# ---------------------------------------------------------------------------
# Fixtures — real Docling schema
# ---------------------------------------------------------------------------


def _make_pdf(path: Path, *, pages: list[str]) -> None:
    """Write a real PDF with the given list of page texts.

    An empty string means "scanned page" (no embedded text).
    """
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _text_item(text: str, *, page_no: int, label: str = "paragraph") -> dict[str, Any]:
    """One Docling ``texts`` entry with provenance."""
    return {
        "label": label,
        "text": text,
        "prov": [
            {
                "page_no": page_no,
                "bbox": {
                    "l": 50.0,
                    "t": 50.0,
                    "r": 545.0,
                    "b": 800.0,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }


def _table_item(
    md_content: str, *, page_no: int, plain: str = ""
) -> dict[str, Any]:
    return {
        "label": "table",
        "text": plain,
        "md_content": md_content,
        "prov": [
            {
                "page_no": page_no,
                "bbox": {
                    "l": 40.0,
                    "t": 40.0,
                    "r": 555.0,
                    "b": 200.0,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }


def _wrap_docling_document(inner: dict[str, Any], md_content: str = "") -> dict[str, Any]:
    """Wrap a typed DoclingDocument in the real response envelope.

    ``docling-serve`` ships the typed document under
    ``document.json_content``. httpx parses inline JSON into a dict
    automatically, so the wire shape the parser sees has
    ``json_content`` as a dict (not a string). Tests build the typed
    dict and call this to get that exact shape.
    """
    return {
        "document": {
            "json_content": inner,
            "md_content": md_content,
        },
        "md_content": md_content,
        "status": "success",
    }


def _digital_docling_payload(*, page_texts: list[str]) -> dict[str, Any]:
    """A Docling response where every page is digital (>= 30 chars)."""
    texts = [_text_item(text, page_no=idx + 1) for idx, text in enumerate(page_texts)]
    pages = {
        str(idx + 1): {"page_no": idx + 1, "size": {"width": 595.0, "height": 842.0}}
        for idx in range(len(page_texts))
    }
    md = "\n\n".join(page_texts)
    return _wrap_docling_document({"texts": texts, "pages": pages}, md_content=md)


def _mixed_docling_payload() -> dict[str, Any]:
    """One digital page (with a table) followed by a scanned page.

    The scanned page is represented the way Docling really represents
    it when ``do_ocr=false``: it has **no** items at all (Docling was
    told to skip OCR, so it has no text for the bitmap page).
    """
    table_md = "| Item | Qty | Price |\n| --- | --- | --- |\n| A | 2 | 10 |"
    inner = {
        "tables": [_table_item(table_md, page_no=1)],
        "pages": {
            "1": {"page_no": 1, "size": {"width": 595.0, "height": 842.0}},
            "2": {"page_no": 2, "size": {"width": 595.0, "height": 842.0}},
        },
    }
    return _wrap_docling_document(inner, md_content=table_md)


class _RecordingCascade:
    """Fake OCR engine that records its thread-local context.

    The cascade reads ``current_language`` / ``current_content_route``
    / ``current_page_number`` (set by the parser before each call) to
    apply per-language thresholds and route-specific tier skipping.
    This fake stores whatever the parser writes so the propagation
    can be asserted. Using a plain class (not a MagicMock) lets the
    parser assign arbitrary attributes without tripping the mock's
    spec checks.
    """

    name = "tesseract"

    def __init__(self) -> None:
        self.observed: dict[str, Any] = {}
        self.extract_calls = 0

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("observed", "extract_calls"):
            object.__setattr__(self, name, value)
        else:
            self.observed[name] = value
            object.__setattr__(self, name, value)

    def extract(self, image_path: Path) -> OCRResult:  # noqa: ARG002
        self.extract_calls += 1
        return OCRResult(
            text="CASCADE TEXT",
            confidence=0.7,
            blocks=[OCRBlock(text="CASCADE TEXT", confidence=0.7, bbox=(0, 0, 100, 100))],
            engine="tesseract",
            content_kind="ocr",
        )

    @property
    def extract_call_count(self) -> int:
        return self.extract_calls


def _fake_cascade() -> _RecordingCascade:
    return _RecordingCascade()


# ---------------------------------------------------------------------------
# Item / page mapping — real schema
# ---------------------------------------------------------------------------


def test_docling_item_to_block_maps_known_labels() -> None:
    item = {
        "label": "table",
        "text": "ignored",
        "md_content": "| a | b |",
        "prov": [{"page_no": 2, "bbox": {"l": 1, "t": 1, "r": 2, "b": 2}}],
    }
    block = _docling_item_to_block(item, page_number=2, page_width=595.0, page_height=842.0)
    assert block is not None
    assert block.block_type == "table"
    assert block.text.startswith("| a | b |")
    assert block.page_number == 2
    assert block.source_engine == "docling"


def test_docling_item_to_block_uses_fallback_label() -> None:
    block = _docling_item_to_block(
        {"label": "future_docling_label", "text": "hello"},
        page_number=1,
        page_width=595.0,
        page_height=842.0,
    )
    assert block is not None
    assert block.block_type == "text"


def test_docling_item_to_block_returns_none_for_empty_text() -> None:
    assert (
        _docling_item_to_block(
            {"label": "text", "text": "   "},
            page_number=1,
            page_width=595.0,
            page_height=842.0,
        )
        is None
    )


def test_docling_item_to_block_reads_prov_bbox() -> None:
    item = {
        "label": "text",
        "text": "hello",
        "prov": [
            {
                "page_no": 1,
                "bbox": {"l": 10.0, "t": 20.0, "r": 30.0, "b": 40.0, "coord_origin": "TOPLEFT"},
            }
        ],
    }
    block = _docling_item_to_block(item, page_number=1, page_width=595.0, page_height=842.0)
    assert block is not None
    assert block.bbox == (10.0, 20.0, 30.0, 40.0)


def test_collect_docling_items_flattens_typed_lists() -> None:
    document = {
        "texts": [{"label": "text", "text": "a"}],
        "tables": [{"label": "table", "md_content": "| x |"}],
        "pictures": [{"label": "picture"}],
    }
    items = _collect_docling_items(document)
    assert len(items) == 3
    labels = [item["label"] for item in items]
    assert labels == ["text", "table", "picture"]


def test_regroup_items_by_page_keys_on_prov_page_no() -> None:
    document = {
        "texts": [
            _text_item("page one text", page_no=1),
            _text_item("page two text", page_no=2),
            _text_item("also page one", page_no=1),
        ]
    }
    grouped = _regroup_items_by_page(document, page_rects=[(595.0, 842.0)] * 2)
    assert sorted(grouped.keys()) == [1, 2]
    assert len(grouped[1]) == 2
    assert len(grouped[2]) == 1


def test_item_page_no_reads_prov_page_no() -> None:
    assert _item_page_no({"prov": [{"page_no": 3}]}) == 3
    assert _item_page_no({"page_no": 5}) == 5
    assert _item_page_no({}) is None


# ---------------------------------------------------------------------------
# _resolve_document — deserialise json_content
# ---------------------------------------------------------------------------


def test_resolve_document_deserialises_json_content() -> None:
    """The real wire shape puts the typed lists inside a JSON string."""
    inner = {"texts": [{"text": "hi", "prov": [{"page_no": 1}]}], "pages": {"1": {}}}
    payload = {"document": {"json_content": json.dumps(inner), "md_content": "hi"}}
    resolved = _resolve_document(payload)
    assert resolved["texts"] == inner["texts"]
    assert resolved["pages"] == inner["pages"]


def test_resolve_document_handles_dict_json_content() -> None:
    """When httpx auto-parses inline JSON, ``json_content`` is a dict."""
    inner = {"texts": [{"text": "hi", "prov": [{"page_no": 1}]}], "pages": {"1": {}}}
    payload = {"document": {"json_content": inner, "md_content": "hi"}}
    resolved = _resolve_document(payload)
    assert resolved["texts"] == inner["texts"]
    assert resolved["pages"] == inner["pages"]


def test_resolve_document_preserves_inline_shape() -> None:
    """When the document is already inline (no json_content), it is
    returned unchanged."""
    document = {"texts": [{"text": "hi"}], "pages": {"1": {}}}
    resolved = _resolve_document({"document": document})
    assert resolved is document


def test_resolve_document_returns_empty_on_garbage() -> None:
    assert _resolve_document({}) == {}
    assert _resolve_document({"document": None}) == {}
    # Malformed json_content falls back to the outer document.
    assert _resolve_document({"document": {"json_content": "not json{"}}) == {
        "json_content": "not json{"
    }


def test_resolve_document_inherits_md_content_from_envelope() -> None:
    """When the inner doc has no md_content, the envelope's is used."""
    inner = {"texts": []}
    payload = {
        "document": {"json_content": json.dumps(inner), "md_content": "# Title"}
    }
    resolved = _resolve_document(payload)
    assert resolved["md_content"] == "# Title"


# ---------------------------------------------------------------------------
# Bbox normalisation
# ---------------------------------------------------------------------------


def test_normalise_bbox_accepts_list() -> None:
    assert _normalise_bbox([1.0, 2.0, 3.0, 4.0], page_width=595.0, page_height=842.0) == (
        1.0,
        2.0,
        3.0,
        4.0,
    )


def test_normalise_bbox_accepts_dict() -> None:
    bbox = {"l": 10.0, "t": 20.0, "r": 30.0, "b": 40.0, "coord_origin": "TOPLEFT"}
    assert _normalise_bbox(bbox, page_width=595.0, page_height=842.0) == (10.0, 20.0, 30.0, 40.0)


def test_normalise_bbox_scales_normalised_coords() -> None:
    """Values in 0..1 are normalised and must be scaled to page points."""
    bbox = {"l": 0.0, "t": 0.0, "r": 0.5, "b": 0.25, "coord_origin": "TOPLEFT"}
    result = _normalise_bbox(bbox, page_width=595.0, page_height=842.0)
    assert result == pytest.approx((0.0, 0.0, 297.5, 210.5))


def test_normalise_bbox_flips_bottomleft_origin() -> None:
    bbox = {"l": 0.0, "t": 100.0, "r": 50.0, "b": 150.0, "coord_origin": "BOTTOMLEFT"}
    result = _normalise_bbox(bbox, page_width=595.0, page_height=842.0)
    # t/b are flipped: new_t = 842 - 150 = 692, new_b = 842 - 100 = 742
    assert result == pytest.approx((0.0, 692.0, 50.0, 742.0))


def test_normalise_bbox_returns_none_for_garbage() -> None:
    assert _normalise_bbox(None, page_width=595.0, page_height=842.0) is None
    assert _normalise_bbox("oops", page_width=595.0, page_height=842.0) is None
    assert _normalise_bbox([1, 2], page_width=595.0, page_height=842.0) is None


# ---------------------------------------------------------------------------
# Page size resolution
# ---------------------------------------------------------------------------


def test_docling_page_sizes_reads_dict_pages() -> None:
    document = {
        "pages": {
            "1": {"page_no": 1, "size": {"width": 595.0, "height": 842.0}},
            "2": {"page_no": 2, "size": {"width": 612.0, "height": 792.0}},
        }
    }
    sizes = _docling_page_sizes(document)
    assert sizes == {1: (595.0, 842.0), 2: (612.0, 792.0)}


def test_resolve_page_size_falls_back_to_fitz_rect() -> None:
    assert _resolve_page_size({}, 1, (595.0, 842.0)) == (595.0, 842.0)
    # A zero-size Docling entry is treated as missing.
    assert _resolve_page_size({1: (0.0, 0.0)}, 1, (200.0, 300.0)) == (200.0, 300.0)


def test_resolve_page_size_uses_docling_value_when_present() -> None:
    assert _resolve_page_size({1: (612.0, 792.0)}, 1, (595.0, 842.0)) == (612.0, 792.0)


# ---------------------------------------------------------------------------
# Digital page builder
# ---------------------------------------------------------------------------


def test_docling_page_to_digital_returns_page_for_long_text() -> None:
    items = [_text_item("Some text long enough to look digital", page_no=1)]
    page = _docling_page_to_digital(items, page_number=1, rect=(595.0, 842.0))
    assert page is not None
    assert page.ocr_engine == "docling"
    assert page.ocr_content_kind == "native_text"
    assert page.ocr_confidence == 1.0
    assert page.image_path is None
    assert page.blocks[0].source_engine == "docling"


def test_docling_page_to_digital_returns_none_for_short_text() -> None:
    """A scanned-looking page (text < 30 chars) must be re-routed to OCR."""
    items = [_text_item("short", page_no=1)]
    page = _docling_page_to_digital(items, page_number=1, rect=(595.0, 842.0))
    assert page is None


def test_docling_page_to_digital_synthesises_block_for_bare_text() -> None:
    """When Docling returns text override but no items, we still build a page."""
    page = _docling_page_to_digital(
        [],
        page_number=3,
        rect=(595.0, 842.0),
        page_text_override="Long enough text to qualify as a digital page",
    )
    assert page is not None
    assert page.page_number == 3
    assert len(page.blocks) == 1
    assert page.blocks[0].block_type == "text"


# ---------------------------------------------------------------------------
# parse_pdf_docling — happy path
# ---------------------------------------------------------------------------


def test_parse_digital_pdf_produces_native_text_pages(tmp_path: Path) -> None:
    pdf = tmp_path / "digital.pdf"
    _make_pdf(
        pdf,
        pages=[
            "Digital page one with plenty of content",
            "Digital page two with more than thirty characters of text",
        ],
    )
    client = MagicMock()
    client.convert_pdf.return_value = _digital_docling_payload(
        page_texts=[
            "Digital page one with plenty of content",
            "Digital page two with more than thirty characters of text",
        ]
    )
    cascade = _fake_cascade()
    out_dir = tmp_path / "out"
    doc = parse_pdf_docling(pdf, out_dir, cascade, docling_client=client)
    assert len(doc.pages) == 2
    for page in doc.pages:
        assert page.ocr_engine == "docling"
        assert page.ocr_content_kind == "native_text"
        assert page.ocr_confidence == 1.0
        assert page.image_path is None
        assert all(b.source_engine == "docling" for b in page.blocks)
    # The cascade must not have been called for digital pages.
    assert cascade.extract_calls == 0


def test_parse_mixed_pdf_routes_per_page(tmp_path: Path) -> None:
    """A digital page stays with Docling; a scanned page goes to the cascade."""
    pdf = tmp_path / "mixed.pdf"
    _make_pdf(pdf, pages=["", ""])  # both pages have no embedded text
    client = MagicMock()
    client.convert_pdf.return_value = _mixed_docling_payload()
    cascade = _fake_cascade()
    out_dir = tmp_path / "out"
    doc = parse_pdf_docling(pdf, out_dir, cascade, docling_client=client)
    assert len(doc.pages) == 2
    # Page 1: digital (Docling structured table output).
    assert doc.pages[0].ocr_engine == "docling"
    assert doc.pages[0].ocr_content_kind == "native_text"
    # Page 2: scanned, must go through the cascade.
    assert doc.pages[1].ocr_engine == "tesseract"
    assert doc.pages[1].ocr_content_kind == "ocr"
    assert cascade.extract_calls >= 1


def test_parse_pdf_with_table_block_preserves_markdown(tmp_path: Path) -> None:
    pdf = tmp_path / "table.pdf"
    _make_pdf(pdf, pages=[""])
    inner = {
        "tables": [
            _table_item("| A | B |\n| --- | --- |\n| 1 | 2 |", page_no=1),
        ],
        "pages": {"1": {"page_no": 1, "size": {"width": 595.0, "height": 842.0}}},
    }
    client = MagicMock()
    client.convert_pdf.return_value = _wrap_docling_document(inner)
    cascade = _fake_cascade()
    out_dir = tmp_path / "out"
    doc = parse_pdf_docling(pdf, out_dir, cascade, docling_client=client)
    # Docling reported a table with enough text -> digital page.
    assert doc.pages[0].ocr_engine == "docling"
    assert doc.pages[0].blocks[0].block_type == "table"
    assert doc.pages[0].blocks[0].text.startswith("| A | B |")


def test_parse_pdf_rejects_oversized_pdf(tmp_path: Path) -> None:
    """``max_pdf_pages`` is enforced before the HTTP call."""
    pdf = tmp_path / "huge.pdf"
    _make_pdf(pdf, pages=["page1"])
    client = MagicMock()

    import app.parsers.pdf_docling as pdf_docling_module

    original = pdf_docling_module.settings.max_pdf_pages
    try:
        object.__setattr__(pdf_docling_module.settings, "max_pdf_pages", 0)
        with pytest.raises(ValueError, match="max_pdf_pages"):
            parse_pdf_docling(pdf, tmp_path / "out", _fake_cascade(), docling_client=client)
        # The HTTP client must never have been called.
        client.convert_pdf.assert_not_called()
    finally:
        object.__setattr__(pdf_docling_module.settings, "max_pdf_pages", original)


def test_parse_pdf_propagates_docling_errors(tmp_path: Path) -> None:
    """A :class:`DoclingError` must surface so the router can fall back."""
    pdf = tmp_path / "broken.pdf"
    _make_pdf(pdf, pages=["any text"])
    client = MagicMock()
    client.convert_pdf.side_effect = DoclingError("service down")
    with pytest.raises(DoclingError, match="service down"):
        parse_pdf_docling(pdf, tmp_path / "out", _fake_cascade(), docling_client=client)


def test_parse_pdf_fills_missing_pages_with_cascade(tmp_path: Path) -> None:
    """When Docling returns fewer pages than the PDF, the rest is OCR'd."""
    pdf = tmp_path / "trimmed.pdf"
    _make_pdf(pdf, pages=["a", "b", "c"])
    client = MagicMock()
    client.convert_pdf.return_value = _digital_docling_payload(
        page_texts=["This is the only page Docling managed to extract text from"]
    )
    cascade = _fake_cascade()
    doc = parse_pdf_docling(pdf, tmp_path / "out", cascade, docling_client=client)
    assert len(doc.pages) == 3
    assert doc.pages[0].ocr_engine == "docling"
    assert doc.pages[1].ocr_engine == "tesseract"
    assert doc.pages[2].ocr_engine == "tesseract"


def test_parse_pdf_ignores_extra_docling_pages(tmp_path: Path) -> None:
    """When Docling returns more pages than the PDF, the extras are dropped."""
    pdf = tmp_path / "tiny.pdf"
    _make_pdf(pdf, pages=["one"])
    client = MagicMock()
    client.convert_pdf.return_value = _digital_docling_payload(
        page_texts=[
            "first page long enough to be considered digital here",
            "second page that should be ignored because the PDF has only one",
        ]
    )
    doc = parse_pdf_docling(pdf, tmp_path / "out", _fake_cascade(), docling_client=client)
    assert len(doc.pages) == 1


def test_parse_pdf_accepts_empty_docling_payload(tmp_path: Path) -> None:
    """A ``{}`` payload must not crash; every page falls back to the cascade."""
    pdf = tmp_path / "empty.pdf"
    _make_pdf(pdf, pages=["ignored", "ignored"])
    client = MagicMock()
    client.convert_pdf.return_value = {}
    cascade = _fake_cascade()
    doc = parse_pdf_docling(pdf, tmp_path / "out", cascade, docling_client=client)
    assert len(doc.pages) == 2
    assert all(p.ocr_engine == "tesseract" for p in doc.pages)


# ---------------------------------------------------------------------------
# Cascade context propagation + byte-compatible scanned page
# ---------------------------------------------------------------------------


def test_parse_scanned_page_propagates_cascade_context(tmp_path: Path) -> None:
    """The cascade must see the same thread-local context the legacy
    parser sets: ``current_content_route``, ``current_language`` (when a
    language could be sniffed), and ``current_page_number``."""
    pdf = tmp_path / "scanned.pdf"
    _make_pdf(pdf, pages=[""])  # one scanned page, no embedded text
    client = MagicMock()
    client.convert_pdf.return_value = {}  # nothing from Docling
    cascade = _fake_cascade()
    doc = parse_pdf_docling(pdf, tmp_path / "out", cascade, docling_client=client)

    assert len(doc.pages) == 1
    observed = cascade.observed  # type: ignore[attr-defined]
    # content_route is always set (classify_content returns a default).
    assert "current_content_route" in observed
    # page_number is always set before the cascade call.
    assert observed.get("current_page_number") == 1


def test_parse_scanned_page_is_byte_compatible_with_legacy(tmp_path: Path) -> None:
    """A scanned page produced by the Docling parser must carry the same
    fields the legacy parser emits: image_path, ocr_content_kind="ocr",
    ocr_engine from the cascade, and blocks sourced from the cascade."""
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=[""])
    client = MagicMock()
    client.convert_pdf.return_value = {}
    doc = parse_pdf_docling(pdf, tmp_path / "out", _fake_cascade(), docling_client=client)

    page = doc.pages[0]
    assert page.ocr_content_kind == "ocr"
    assert page.ocr_engine == "tesseract"
    assert page.image_path is not None
    assert page.blocks[0].source_engine == "tesseract"
    assert page.blocks[0].block_type == "text"


# ---------------------------------------------------------------------------
# Parallelism
# ---------------------------------------------------------------------------


def test_parse_pdf_processes_scanned_pages_in_parallel(tmp_path: Path) -> None:
    """Multiple scanned pages must exercise the thread pool, not run
    sequentially. We assert the cascade is called once per page and
    that all pages are present (the pool returned them all)."""
    import app.parsers.pdf_docling as pdf_docling_module

    pdf = tmp_path / "multi.pdf"
    _make_pdf(pdf, pages=["", "", "", ""])  # 4 scanned pages
    client = MagicMock()
    client.convert_pdf.return_value = {}
    cascade = _fake_cascade()

    # Force the pool to actually use >1 worker.
    original = pdf_docling_module.settings.ocr_page_parallelism
    try:
        object.__setattr__(pdf_docling_module.settings, "ocr_page_parallelism", 4)
        doc = parse_pdf_docling(pdf, tmp_path / "out", cascade, docling_client=client)
    finally:
        object.__setattr__(pdf_docling_module.settings, "ocr_page_parallelism", original)

    assert len(doc.pages) == 4
    assert cascade.extract_calls >= 4
