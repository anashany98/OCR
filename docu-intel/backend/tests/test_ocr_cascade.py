"""Tests for the cascade OCR engine and its factory.

These tests cover the cascade in isolation — no Tesseract binary, no
PaddleOCR model load, no DB. They use lightweight fake engines so the
escalation logic can be exercised quickly and deterministically.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.ocr.base import OCRBlock, OCRResult
from app.ocr import cascading
from app.ocr.cascading import CascadingOCREngine
from app.ocr.factory import get_ocr_engine, get_ocr_engine_class
from app.ocr.tesseract import TesseractOCREngine


class _RecordingEngine:
    """Fake OCR engine that records calls and returns a canned result."""

    def __init__(self, name: str, result: OCRResult) -> None:
        self.name = name
        self._result = result
        self.calls = 0

    def extract(self, image_path: Path) -> OCRResult:
        self.calls += 1
        return self._result


def _result(text: str, confidence: float = 0.8, engine: str = "fake") -> OCRResult:
    return OCRResult(
        text=text,
        confidence=confidence,
        blocks=[OCRBlock(text=text, confidence=confidence, bbox=(0.0, 0.0, 10.0, 10.0))],
        engine=engine,
    )


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_factory_returns_tesseract_class_for_tesseract_config(monkeypatch):
    from app.core.config import settings
    from app.ocr import paddle, tesseract

    monkeypatch.setattr(settings, "ocr_engine", "tesseract")
    # Clear the lru_cache so the new config takes effect.
    get_ocr_engine_class.cache_clear()
    try:
        cls = get_ocr_engine_class()
        assert cls is tesseract.TesseractOCREngine
    finally:
        get_ocr_engine_class.cache_clear()


def test_factory_returns_cascading_class_for_cascading_config(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_engine", "cascading")
    get_ocr_engine_class.cache_clear()
    try:
        cls = get_ocr_engine_class()
        instance = cls()
        assert isinstance(instance, CascadingOCREngine)
        assert isinstance(instance.primary, TesseractOCREngine)
    finally:
        get_ocr_engine_class.cache_clear()


def test_factory_caches_results(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_engine", "cascading")
    get_ocr_engine_class.cache_clear()
    try:
        first = get_ocr_engine_class()
        second = get_ocr_engine_class()
        assert first is second
    finally:
        get_ocr_engine_class.cache_clear()


# ---------------------------------------------------------------------------
# Cascade escalation
# ---------------------------------------------------------------------------


def test_cascade_keeps_primary_when_result_is_acceptable(tmp_path: Path):
    primary = _RecordingEngine("fake_primary", _result("A" * 60, confidence=0.9, engine="tesseract"))
    fallback = _RecordingEngine("fake_fallback", _result("B" * 200, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "tesseract"
    assert result.text == "A" * 60
    assert primary.calls == 1
    assert fallback.calls == 0
    assert cascade.name == "fake_primary"


def test_cascade_escalates_to_fallback_when_primary_text_is_too_short(tmp_path: Path):
    primary = _RecordingEngine("fake_primary", _result("short", confidence=0.9, engine="tesseract"))
    fallback = _RecordingEngine("fake_fallback", _result("C" * 100, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "paddleocr"
    assert result.text == "C" * 100
    assert primary.calls == 1
    assert fallback.calls == 1
    assert cascade.name == "fake_fallback"


def test_cascade_escalates_when_primary_confidence_below_threshold(tmp_path: Path):
    primary = _RecordingEngine("fake_primary", _result("D" * 100, confidence=0.3, engine="tesseract"))
    fallback = _RecordingEngine("fake_fallback", _result("E" * 100, confidence=0.9, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "paddleocr"
    assert primary.calls == 1
    assert fallback.calls == 1


def test_quality_penalizes_long_symbol_noise():
    clean = _result("Factura 2026/154 total 123,45 euros", confidence=0.93, engine="tesseract")
    noisy = _result("%%%% !!!!! #### " * 80, confidence=0.41, engine="paddleocr")

    assert cascading._quality(clean) > cascading._quality(noisy)


def test_cascade_does_not_replace_clean_text_with_long_symbol_noise(tmp_path: Path):
    primary = _RecordingEngine("fake_primary", _result("Factura 2026/154 total 123,45 euros", 0.93, "tesseract"))
    fallback = _RecordingEngine("fake_fallback", _result("%%%% !!!!! #### " * 80, 0.41, "paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=50, min_confidence=0.95)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "tesseract"
    assert fallback.calls == 1


def test_cascade_keeps_primary_when_fallback_is_not_strictly_better(tmp_path: Path):
    """Conservative heuristic: if the primary is unacceptable but the
    fallback doesn't beat it on either text length or confidence, keep
    the primary so we don't pay the paddle cost on every page."""
    primary = _RecordingEngine("fake_primary", _result("F" * 10, confidence=0.9, engine="tesseract"))
    fallback = _RecordingEngine("fake_fallback", _result("G" * 5, confidence=0.5, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "tesseract"
    assert result.text == "F" * 10
    assert primary.calls == 1
    assert fallback.calls == 1  # was called, but lost the comparison


def test_cascade_logs_and_tracks_fallback_exception(tmp_path: Path, caplog, monkeypatch):
    class _BoomEngine(_RecordingEngine):
        def extract(self, image_path: Path) -> OCRResult:
            super().extract(image_path)
            raise RuntimeError("paddle init failed")

    fallback_events: list[tuple[str, str]] = []
    tier_events: list[str] = []
    monkeypatch.setattr(
        cascading,
        "track_ocr_cascade_fallback",
        lambda engine_name, reason: fallback_events.append((engine_name, reason)),
        raising=False,
    )
    monkeypatch.setattr(
        cascading,
        "track_ocr_tier_used",
        lambda tier: tier_events.append(tier),
        raising=False,
    )

    primary = _RecordingEngine("fake_primary", _result("short", confidence=0.9, engine="tesseract"))
    fallback = _BoomEngine("fake_fallback", _result("ignored", engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    with caplog.at_level(logging.WARNING, logger="app.ocr.cascading"):
        result = cascade.extract(image)

    assert result.engine == "tesseract"
    assert "fake_fallback" in caplog.text
    assert "paddle init failed" in caplog.text
    assert fallback_events == [("fake_fallback", "paddle init failed")]
    assert tier_events == ["fake_primary"]


def test_cascade_keeps_primary_when_fallback_raises(tmp_path: Path):
    class _BoomEngine(_RecordingEngine):
        def extract(self, image_path: Path) -> OCRResult:
            super().extract(image_path)
            raise RuntimeError("paddle init failed")

    primary = _RecordingEngine("fake_primary", _result("H" * 100, confidence=0.9, engine="tesseract"))
    fallback = _BoomEngine("fake_fallback", _result("ignored", engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    # Primary was acceptable, fallback never gets a chance to win.
    assert result.engine == "tesseract"


def test_cascade_name_reflects_last_winner(tmp_path: Path):
    """The dynamic ``name`` property mirrors the last engine that produced
    a winning result, so the admin UI can break down cascade share."""
    primary_good = _RecordingEngine("primary", _result("I" * 100, confidence=0.9, engine="tesseract"))
    primary_bad = _RecordingEngine("primary", _result("x", confidence=0.9, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("J" * 100, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary_bad, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    cascade.extract(image)
    assert cascade.name == "fallback"

    # Swap to a primary that produces an acceptable result.
    cascade.primary = primary_good
    cascade.extract(image)
    assert cascade.name == "primary"
