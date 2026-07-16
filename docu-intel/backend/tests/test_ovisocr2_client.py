from __future__ import annotations

from pathlib import Path

import httpx
from PIL import Image

from app.ocr.ovisocr2 import (
    OvisOCR2Config,
    OvisOCR2Engine,
    OvisOCR2Error,
    OvisOCR2InputTooLarge,
)


def _config(**overrides) -> OvisOCR2Config:
    values = dict(
        enabled=True,
        endpoint="http://ovisocr2:8000",
        model="ATH-MaaS/OvisOCR2",
        revision="77bfe9462d1e6f8965ee6698f08ea8ede580912c",
        timeout_seconds=10,
        connect_timeout_seconds=1,
        max_tokens=100,
        max_response_bytes=10_000,
        keep_visual_regions=True,
        tier4_primary=True,
    )
    values.update(overrides)
    return OvisOCR2Config(**values)


def _image(path: Path) -> None:
    Image.new("RGB", (448, 448), color="white").save(path)


def test_client_posts_internal_contract_and_preserves_pinned_revision(tmp_path: Path):
    image = tmp_path / "página con espacios.png"
    _image(image)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers["content-type"]
        return httpx.Response(
            200,
            json={
                "schema_version": "1",
                "model": "ATH-MaaS/OvisOCR2",
                "revision": "77bfe9462d1e6f8965ee6698f08ea8ede580912c",
                "markdown": "Factura 42\n<table><tr><td>10</td></tr></table>",
                "finish_reason": "stop",
                "warnings": [],
            },
        )

    engine = OvisOCR2Engine(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    engine.set_context(document_id=7, page_number=2, baseline=None)
    result = engine.extract(image)

    assert seen["url"].endswith("/v1/ocr")
    assert "multipart/form-data" in seen["content_type"]
    assert result.confidence is None
    assert result.engine == "ovisocr2"
    assert result.engine_version == "ovisocr2:77bfe9462d1e6f8965ee6698f08ea8ede580912c"
    assert any(block.block_type == "table" for block in result.blocks)


def test_client_rejects_incompatible_schema(tmp_path: Path):
    image = tmp_path / "page.png"
    _image(image)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"schema_version": "2", "markdown": "x"})

    engine = OvisOCR2Engine(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    engine.set_context(baseline=None)

    try:
        engine.extract(image)
    except OvisOCR2Error as exc:
        assert "schema" in str(exc).lower()
    else:
        raise AssertionError("incompatible schemas must be rejected")


def test_client_requires_exact_model_and_pinned_revision(tmp_path: Path):
    image = tmp_path / "page.png"
    _image(image)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"schema_version": "1", "markdown": "x", "finish_reason": "stop"},
        )

    engine = OvisOCR2Engine(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    engine.set_context(baseline=None)

    try:
        engine.extract(image)
    except OvisOCR2Error as exc:
        assert "model" in str(exc).lower()
    else:
        raise AssertionError("missing model and revision must be rejected")


def test_client_does_not_retry_a_4xx(tmp_path: Path):
    image = tmp_path / "page.png"
    _image(image)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"detail": "invalid"})

    engine = OvisOCR2Engine(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    engine.set_context(baseline=None)

    try:
        engine.extract(image)
    except OvisOCR2Error:
        pass
    else:
        raise AssertionError("4xx must surface as a controlled OCR error")
    assert calls == 1


def test_client_deduplicates_service_and_parser_warnings(tmp_path: Path):
    image = tmp_path / "page.png"
    _image(image)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "1",
                "model": "ATH-MaaS/OvisOCR2",
                "revision": "77bfe9462d1e6f8965ee6698f08ea8ede580912c",
                "markdown": "OCR truncated",
                "finish_reason": "length",
                "warnings": ["truncated_output"],
            },
        )

    engine = OvisOCR2Engine(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    engine.set_context(baseline=None)

    assert engine.extract(image).warnings == ["truncated_output"]


def test_client_skips_oversized_image_before_calling_ovis(tmp_path: Path):
    image = tmp_path / "large.png"
    Image.new("RGB", (1200, 1200), color="white").save(image)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    engine = OvisOCR2Engine(
        _config(max_pixels=1_000_000),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    engine.set_context(baseline=None)

    try:
        engine.extract(image)
    except OvisOCR2InputTooLarge as exc:
        assert "pixels" in str(exc)
    else:
        raise AssertionError("oversized images must be skipped before the HTTP call")
    assert calls == 0
