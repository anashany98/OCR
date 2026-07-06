from __future__ import annotations

import base64
import json
from pathlib import Path

from app.ai.nuextract_client import NuExtractClient
from app.ocr.base import OCRBlock, OCRResult
from app.ocr.cascading import CascadingOCREngine
from app.ocr.nuextract_ocr import NuExtractOCREngine
from app.services.hyperextract.service import (
    HyperExtractService,
    nuextract_template_from_hyperextract,
)
from app.services.hyperextract.templates import HyperExtractTemplate


def test_nuextract_client_builds_markdown_payload(tmp_path: Path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"png-bytes")
    monkeypatch.setattr("app.ai.nuextract_client.settings.nuextract_markdown_temperature", 0.2)
    monkeypatch.setattr("app.ai.nuextract_client.settings.nuextract_enable_thinking", False)

    payload = NuExtractClient(
        base_url="http://nuextract/v1",
        model="numind/NuExtract3",
    ).build_markdown_payload(image)

    assert payload["model"] == "numind/NuExtract3"
    assert payload["temperature"] == 0.2
    assert payload["chat_template_kwargs"] == {"mode": "markdown", "enable_thinking": False}
    data_url = payload["messages"][0]["content"][0]["image_url"]["url"]
    assert data_url == "data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii")


def test_nuextract_client_builds_structured_payload_without_structured_mode(
    tmp_path: Path,
    monkeypatch,
):
    image = tmp_path / "page.png"
    image.write_bytes(b"png-bytes")
    monkeypatch.setattr("app.ai.nuextract_client.settings.nuextract_extraction_temperature", 0.2)
    template = {"fields": {"total": "number"}}

    payload = NuExtractClient(
        base_url="http://nuextract/v1",
        model="numind/NuExtract3",
    ).build_extraction_payload(image, template)

    kwargs = payload["chat_template_kwargs"]
    assert "mode" not in kwargs
    assert kwargs["template"] == json.dumps(template, indent=4, ensure_ascii=False)
    assert json.loads(kwargs["template"]) == template


def test_nuextract_ocr_engine_returns_ocr_result(tmp_path: Path):
    image = tmp_path / "page.png"
    image.write_bytes(b"png-bytes")

    class _Client:
        async def markdown_from_image(self, image_path):
            assert Path(image_path) == image
            return "# Factura\nTotal 123,45"

    result = NuExtractOCREngine(client=_Client(), confidence=0.77).extract(image)

    assert result.text == "# Factura\nTotal 123,45"
    assert result.confidence == 0.77
    assert result.engine == "nuextract3"
    assert result.blocks == [
        OCRBlock(
            text="# Factura\nTotal 123,45",
            confidence=0.77,
            bbox=None,
            block_type="markdown",
        )
    ]


def test_cascading_uses_dots_fallback_when_nuextract_fails(tmp_path: Path):
    image = tmp_path / "page.png"
    image.write_bytes(b"png-bytes")

    class _Engine:
        def __init__(self, name: str, text: str, confidence: float = 0.2) -> None:
            self.name = name
            self.calls = 0
            self.result = OCRResult(text=text, confidence=confidence, blocks=[], engine=name)

        def extract(self, image_path: Path) -> OCRResult:
            self.calls += 1
            return self.result

    class _Boom(_Engine):
        def extract(self, image_path: Path) -> OCRResult:
            self.calls += 1
            raise RuntimeError("nuextract down")

    primary = _Engine("tesseract", "x")
    fallback = _Engine("paddleocr", "y")
    nuextract = _Boom("nuextract3", "")
    dots = _Engine("dots_mocr", "Texto limpio desde Dots", confidence=0.95)
    cascade = CascadingOCREngine(
        primary=primary,
        fallback=fallback,
        vlm_ocr=nuextract,
        tier4_fallback=dots,
        tier4_quality_threshold=0.8,
    )

    result = cascade.extract(image)

    assert result.engine == "dots_mocr"
    assert nuextract.calls == 1
    assert dots.calls == 1


def test_template_converter_maps_basic_types():
    template = HyperExtractTemplate(
        name="factura",
        document_type="factura",
        description="",
        version=1,
        system_prompt="",
        fields=[
            {"name": "proveedor", "type": "string"},
            {"name": "total", "type": "decimal"},
            {
                "name": "lineas",
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"cantidad": {"type": "integer"}},
                },
            },
            {"name": "estado", "type": "enum", "values": ["pendiente", "pagada"]},
        ],
    )

    converted = nuextract_template_from_hyperextract(template)

    assert converted["fields"]["proveedor"] == "string"
    assert converted["fields"]["total"] == "number"
    assert converted["fields"]["lineas"] == [{"cantidad": "integer"}]
    assert converted["fields"]["estado"] == ["pendiente", "pagada"]


def test_hyperextract_visual_uses_direct_json(monkeypatch, tmp_path: Path):
    image = tmp_path / "page.png"
    image.write_bytes(b"png-bytes")
    monkeypatch.setattr("app.services.hyperextract.service.settings.hyperextract_enabled", True)
    monkeypatch.setattr("app.services.hyperextract.service.settings.nuextract_enabled", True)
    monkeypatch.setattr(
        "app.services.hyperextract.service.settings.nuextract_hyperextract_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.hyperextract.service.settings.nuextract_model",
        "numind/NuExtract3",
    )

    class _Client:
        async def extract_from_image(self, image_path, template):
            return {"fields": {"total": 123.45}, "warnings": []}

    monkeypatch.setattr("app.services.hyperextract.service.NuExtractClient", lambda: _Client())
    service = HyperExtractService(provider_name="nuextract_visual")

    envelope = service.extract_from_text("doc-1", "OCR fallback", "factura", image_path=image)

    assert envelope["status"] == "success"
    assert envelope["provider"] == "nuextract_visual"
    assert envelope["fields"]["total"] == 123.45


def test_hyperextract_visual_falls_back_without_image(monkeypatch):
    monkeypatch.setattr("app.services.hyperextract.service.settings.hyperextract_enabled", True)
    monkeypatch.setattr("app.services.hyperextract.service.settings.nuextract_enabled", True)
    monkeypatch.setattr(
        "app.services.hyperextract.service.settings.nuextract_hyperextract_enabled",
        True,
    )
    service = HyperExtractService(
        provider_name="nuextract_visual",
        base_url="http://llm/v1",
        model="model",
    )
    monkeypatch.setattr(
        service,
        "_call_provider",
        lambda **_kwargs: '{"fields":{"source":"text"},"entities":[],"relations":[]}',
    )

    envelope = service.extract_from_text("doc-1", "texto", "factura")

    assert envelope["status"] == "success"
    assert envelope["fields"]["source"] == "text"


def test_nuextract_disabled_keeps_hyperextract_text_flow(monkeypatch):
    monkeypatch.setattr("app.services.hyperextract.service.settings.hyperextract_enabled", True)
    monkeypatch.setattr("app.services.hyperextract.service.settings.nuextract_enabled", False)
    service = HyperExtractService(
        provider_name="openai_compatible",
        base_url="http://llm/v1",
        model="model",
    )
    monkeypatch.setattr(
        service,
        "_call_provider",
        lambda **_kwargs: '{"fields":{"source":"text"},"entities":[],"relations":[]}',
    )

    envelope = service.extract_from_text("doc-1", "texto", "factura")

    assert envelope["status"] == "success"
    assert envelope["provider"] == "openai_compatible"
    assert envelope["fields"]["source"] == "text"
