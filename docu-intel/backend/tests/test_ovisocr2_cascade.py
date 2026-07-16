from __future__ import annotations

from pathlib import Path

import pytest

from app.ocr.base import OCRResult
from app.ocr.cascading import CascadingOCREngine
from app.ocr.ovisocr2 import OvisOCR2InputTooLarge
from app.ocr.tier4_chain import Tier4EngineChain


class _Engine:
    def __init__(self, name: str, result: OCRResult | Exception) -> None:
        self.name = name
        self.result = result
        self.calls = 0
        self.contexts: list[dict[str, object]] = []

    def set_context(self, **context: object) -> None:
        self.contexts.append(context)

    def extract(self, image_path: Path) -> OCRResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_tier4_chain_uses_independent_fallback_only_after_failure(tmp_path: Path):
    first = _Engine("ovisocr2", RuntimeError("service unavailable"))
    second = _Engine(
        "dots_mocr", OCRResult(text="fallback text", confidence=None, blocks=[], engine="dots_mocr")
    )
    chain = Tier4EngineChain([first, second], max_total_seconds=5)

    result = chain.extract(tmp_path / "page.png")

    assert result.engine == "dots_mocr"
    assert first.calls == second.calls == 1
    assert chain.last_attempts == [
        {"engine": "ovisocr2", "outcome": "failure"},
        {"engine": "dots_mocr", "outcome": "success"},
    ]


def test_tier4_chain_propagates_context_to_each_engine(tmp_path: Path):
    first = _Engine("ovisocr2", OCRResult(text="ok", confidence=None, blocks=[], engine="ovisocr2"))
    second = _Engine(
        "dots_mocr", OCRResult(text="fallback", confidence=None, blocks=[], engine="dots_mocr")
    )
    chain = Tier4EngineChain([first, second], max_total_seconds=5)

    chain.set_context(document_id=7, page_number=3, content_route="standard_ocr", baseline=None)
    chain.extract(tmp_path / "page.png")

    assert first.contexts[0] == {
        "document_id": 7,
        "page_number": 3,
        "content_route": "standard_ocr",
        "baseline": None,
    }
    assert "chain_deadline_monotonic" in first.contexts[-1]
    assert second.contexts[0] == first.contexts[0]


def test_tier4_chain_does_not_pass_an_oversized_page_to_legacy_vlm(tmp_path: Path):
    first = _Engine("ovisocr2", OvisOCR2InputTooLarge("image exceeds pixel limit"))
    second = _Engine(
        "dots_mocr", OCRResult(text="fallback", confidence=None, blocks=[], engine="dots_mocr")
    )
    chain = Tier4EngineChain([first, second], max_total_seconds=5)

    with pytest.raises(OvisOCR2InputTooLarge):
        chain.extract(tmp_path / "page_1_dpi500.jpg")

    assert first.calls == 1
    assert second.calls == 0
    assert chain.last_attempts == [{"engine": "ovisocr2", "outcome": "input_too_large"}]


def test_cascade_does_not_call_external_fallback_for_an_oversized_tier4_page(tmp_path: Path):
    primary = _Engine("tesseract", OCRResult(text="baseline", confidence=0.4, blocks=[]))
    tier4 = _Engine("tier4_chain", OvisOCR2InputTooLarge("image exceeds pixel limit"))
    legacy = _Engine(
        "dots_mocr", OCRResult(text="legacy fallback", confidence=None, blocks=[], engine="dots_mocr")
    )
    cascade = CascadingOCREngine(
        primary=primary,
        fallback=None,
        vlm_ocr=tier4,
        tier4_fallback=legacy,
    )

    result = cascade._try_tier4(
        tmp_path / "page_1_dpi500.jpg",
        OCRResult(text="baseline", confidence=0.4, blocks=[]),
    )

    assert result is None
    assert tier4.calls == 1
    assert legacy.calls == 0


def test_tier4_chain_rejects_a_result_that_arrives_after_its_global_budget(monkeypatch, tmp_path: Path):
    engine = _Engine("ovisocr2", OCRResult(text="late", confidence=None, blocks=[], engine="ovisocr2"))
    chain = Tier4EngineChain([engine], max_total_seconds=0.5)
    clock = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr("app.ocr.tier4_chain.time.monotonic", lambda: next(clock))

    with pytest.raises(TimeoutError, match="time budget"):
        chain.extract(tmp_path / "page.png")

    assert chain.last_attempts == [{"engine": "ovisocr2", "outcome": "chain_timeout"}]
