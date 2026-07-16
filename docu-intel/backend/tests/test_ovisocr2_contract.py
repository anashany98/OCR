"""Contract tests for the versioned OvisOCR2 HTTP boundary."""

from __future__ import annotations

from pathlib import Path

import httpx
from PIL import Image

from app.ocr.ovisocr2 import OvisOCR2Config, OvisOCR2Engine, OvisOCR2Error


def _config() -> OvisOCR2Config:
    return OvisOCR2Config(
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


def test_contract_accepts_the_versioned_service_response(tmp_path: Path):
    image = tmp_path / "page.png"
    Image.new("RGB", (448, 448), color="white").save(image)
    payload = {
        "schema_version": "1",
        "request_id": "a5e549a5-0f23-4512-88ce-d29ce6de0566",
        "model": "ATH-MaaS/OvisOCR2",
        "revision": "77bfe9462d1e6f8965ee6698f08ea8ede580912c",
        "markdown": "texto",
        "blocks": [{"type": "text", "text": "texto"}],
        "finish_reason": "stop",
        "input_pixels": 200704,
        "output_tokens": 1,
        "latency_ms": 10,
        "warnings": [],
    }
    engine = OvisOCR2Engine(
        _config(),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )
    engine.set_context(baseline=None)

    result = engine.extract(image)

    assert result.text == "texto"
    assert result.engine_version.endswith(payload["revision"])
    engine.close()


def test_contract_rejects_missing_pinned_revision(tmp_path: Path):
    image = tmp_path / "page.png"
    Image.new("RGB", (448, 448), color="white").save(image)
    payload = {
        "schema_version": "1",
        "model": "ATH-MaaS/OvisOCR2",
        "markdown": "texto",
        "finish_reason": "stop",
    }
    engine = OvisOCR2Engine(
        _config(),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )
    engine.set_context(baseline=None)

    try:
        engine.extract(image)
    except OvisOCR2Error as exc:
        assert "revision" in str(exc).lower()
    else:
        raise AssertionError("a response without a revision must be rejected")
    engine.close()
