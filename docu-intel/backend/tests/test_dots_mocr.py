from __future__ import annotations

import base64

from app.ocr.dots_mocr import DotsMOCRConfig, DotsMOCREngine


def test_dots_mocr_posts_image_and_parses_blocks(tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"image-bytes")
    calls: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "text": "Texto VLM",
                "confidence": 0.92,
                "blocks": [
                    {
                        "text": "Texto VLM",
                        "confidence": 0.92,
                        "bbox": [1, 2, 30, 40],
                        "block_type": "text",
                    }
                ],
            }

    class _Client:
        def __init__(self, **kwargs):
            calls.append({"init": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, endpoint, *, json, headers):
            calls.append({"endpoint": endpoint, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setattr("app.ocr.dots_mocr.httpx.Client", _Client)

    engine = DotsMOCREngine(
        DotsMOCRConfig(
            enabled=True,
            endpoint="http://vlm.local/ocr",
            api_key="secret",
            timeout_seconds=3.5,
        )
    )

    result = engine.extract(image)

    assert result.engine == "dots_mocr"
    assert result.text == "Texto VLM"
    assert result.confidence == 0.92
    assert result.blocks[0].bbox == (1.0, 2.0, 30.0, 40.0)
    assert calls[0]["init"]["timeout"] == 3.5
    assert calls[1]["endpoint"] == "http://vlm.local/ocr"
    assert calls[1]["headers"] == {"Authorization": "Bearer secret"}
    assert calls[1]["json"]["image_base64"] == base64.b64encode(b"image-bytes").decode("ascii")
