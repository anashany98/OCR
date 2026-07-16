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


def test_cascading_factory_reuses_single_engine_instance(monkeypatch):
    import sys
    from types import ModuleType

    from app.core.config import settings
    from app.ocr import factory

    created: list[str] = []

    class _FakeTesseract:
        name = "tesseract"

        def __init__(self, **kwargs):
            created.append("tesseract")

    class _FakePaddle:
        name = "paddleocr"

        def __init__(self, **kwargs):
            created.append("paddleocr")

    tesseract_module = ModuleType("app.ocr.tesseract")
    tesseract_module.TesseractOCREngine = _FakeTesseract
    paddle_module = ModuleType("app.ocr.paddle")
    paddle_module.PaddleOCREngine = _FakePaddle
    paddle_module._get_gpu_device = lambda: None
    paddle_module.gpu_has_headroom = lambda: False
    monkeypatch.setitem(sys.modules, "app.ocr.tesseract", tesseract_module)
    monkeypatch.setitem(sys.modules, "app.ocr.paddle", paddle_module)
    monkeypatch.setattr(settings, "ocr_engine", "cascading")
    monkeypatch.setattr(settings, "ocr_cascading_use_pp_structure", False)
    monkeypatch.setattr(settings, "paddleocr_gpu_only", False)
    factory.get_ocr_engine_class.cache_clear()
    if hasattr(factory, "clear_ocr_engine_cache"):
        factory.clear_ocr_engine_cache()

    try:
        first = factory.get_ocr_engine()
        second = factory.get_ocr_engine()
    finally:
        factory.get_ocr_engine_class.cache_clear()
        if hasattr(factory, "clear_ocr_engine_cache"):
            factory.clear_ocr_engine_cache()

    assert first is second
    assert created == ["tesseract", "paddleocr"]


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


def test_cascade_uses_tier4_vlm_when_prior_quality_is_low(tmp_path: Path):
    primary = _RecordingEngine("fake_primary", _result("x", confidence=0.2, engine="tesseract"))
    fallback = _RecordingEngine("fake_fallback", _result("y", confidence=0.2, engine="paddleocr"))
    vlm = _RecordingEngine("fake_vlm", _result("Factura limpia con total 123,45 euros y fecha 01/05/2026", confidence=0.96, engine="dots_mocr"))
    cascade = CascadingOCREngine(
        primary=primary,
        fallback=fallback,
        min_chars=30,
        min_confidence=0.5,
        vlm_ocr=vlm,
        tier4_quality_threshold=0.8,
    )

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "dots_mocr"
    assert cascade.name == "fake_vlm"
    assert vlm.calls == 1


def test_cascade_promotes_coherent_vision_text_when_classical_confidence_is_low(tmp_path: Path):
    primary = _RecordingEngine(
        "fake_primary",
        _result("Texto manuscrito parcialmente legible " * 4, confidence=0.40, engine="tesseract"),
    )
    vision = _RecordingEngine(
        "fake_vlm",
        _result("Texto manuscrito transcrito con referencias y medidas claras " * 4, confidence=0.50, engine="dots_mocr"),
    )
    cascade = CascadingOCREngine(
        primary=primary,
        fallback=None,
        min_chars=30,
        min_confidence=0.70,
        vlm_ocr=vision,
        tier4_quality_threshold=0.62,
    )
    image = tmp_path / "manuscrito.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "dots_mocr"
    assert vision.calls == 1


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


# ---------------------------------------------------------------------------
# S0.6 — Skip Tier 2 when the quality gain is not significant
# ---------------------------------------------------------------------------


def test_should_replace_with_fallback_keeps_primary_when_quality_delta_is_small():
    """When the fallback barely improves the quality score (delta < the
    configured threshold) the cascade should keep the primary result
    instead of paying for Tier 2."""
    from app.ocr.cascading import _should_replace_with_fallback
    from app.core.config import settings

    primary = _result("A" * 50, confidence=0.60, engine="tesseract")
    fallback = _result("B" * 50, confidence=0.65, engine="paddleocr")  # tiny bump

    # The new flag is True by default; primary should be kept.
    assert settings.ocr_cascading_skip_if_no_significant_gain is True
    should, reason = _should_replace_with_fallback(primary, fallback)
    assert should is False
    assert reason == "no_significant_gain"


def test_should_replace_with_fallback_replaces_when_quality_delta_is_large():
    """When the fallback improves the quality score by more than the
    configured threshold the cascade should swap."""
    from app.ocr.cascading import _should_replace_with_fallback

    primary = _result("x" * 10, confidence=0.30, engine="tesseract")
    fallback = _result("Y" * 300, confidence=0.92, engine="paddleocr")  # big win

    should, reason = _should_replace_with_fallback(primary, fallback)
    assert should is True
    assert reason == "ok"


def test_should_replace_with_fallback_uses_alnum_gain_as_escape_hatch():
    """When the quality delta is small but the fallback adds many
    alphanumeric characters (e.g. primary returned mostly symbols and
    the fallback recovered the actual letters), the alnum gain
    threshold lets the swap through."""
    from app.ocr.cascading import _should_replace_with_fallback, _quality, _alnum_count

    # Both texts have very high alphanumeric density (long runs of
    # letters) so the quality score is similar; the only meaningful
    # difference is the extra alphanumeric characters the fallback
    # contributes. The quality delta stays below 0.10 and the
    # alnum_gain branch must let the swap through.
    primary = _result("AAAAAAAAAA", confidence=0.50, engine="tesseract")
    fallback = _result("BBBBBBBBBB" * 4, confidence=0.50, engine="paddleocr")

    # Sanity-check the underlying counts.
    assert _alnum_count(primary.text) == 10
    assert _alnum_count(fallback.text) == 40
    assert _alnum_count(fallback.text) - _alnum_count(primary.text) == 30

    # Lengths differ but the quality delta is dominated by density
    # (both 100% alnum) and confidence (both 0.50) so it stays small.
    p_q = _quality(primary)
    f_q = _quality(fallback)
    assert f_q - p_q < 0.10, f"quality delta too large: {f_q - p_q}"

    should, reason = _should_replace_with_fallback(primary, fallback)
    assert should is True
    assert reason == "alnum_gain"


def test_should_replace_with_fallback_returns_both_weak_when_both_engines_fail():
    """When neither engine produced anything usable the cascade keeps
    the primary (so the user sees *some* text) and reports the reason
    as ``both_weak`` so the admin UI can spot the hard cases."""
    from app.ocr.cascading import _should_replace_with_fallback

    primary = _result("", confidence=0.0, engine="tesseract")
    fallback = _result("", confidence=0.0, engine="paddleocr")

    should, reason = _should_replace_with_fallback(primary, fallback)
    assert should is False
    assert reason == "both_weak"


def test_cascade_skips_tier2_and_tracks_metric_when_gain_is_marginal(tmp_path: Path, monkeypatch):
    """End-to-end: when the fallback is only marginally better than
    the primary the cascade should keep the primary, log the decision
    and record the skip reason in the metrics counter."""
    skip_events: list[str] = []
    monkeypatch.setattr(
        cascading,
        "track_ocr_skip_tier2",
        lambda reason: skip_events.append(reason),
        raising=False,
    )

    # Primary is *not* acceptable (only 10 chars, below min_chars=30),
    # so the cascade escalates to the fallback. The fallback is only
    # marginally better (11 chars, conf 0.30 — same as primary), so
    # the cascade should keep the primary and record the skip.
    primary = _RecordingEngine("primary", _result("A" * 10, confidence=0.30, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 11, confidence=0.30, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "tesseract"
    assert result.text == "A" * 10
    assert primary.calls == 1
    assert fallback.calls == 1  # was called, but lost the comparison
    assert skip_events == ["no_significant_gain"]


def test_cascade_legacy_mode_swaps_on_any_positive_delta(tmp_path: Path, monkeypatch):
    """With ``ocr_cascading_skip_if_no_significant_gain=False`` the
    cascade restores the legacy behaviour: any positive quality delta
    is enough to swap to Tier 2. This is the safety valve to disable
    the new behaviour per deployment."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_cascading_skip_if_no_significant_gain", False)

    # Primary is *not* acceptable (only 10 chars, below min_chars=30).
    # The fallback is longer (50 chars) and slightly more confident,
    # so the quality delta is positive. With the new flag on, the
    # cascade would keep the primary; with the legacy flag off, the
    # cascade swaps on any positive delta.
    primary = _RecordingEngine("primary", _result("A" * 10, confidence=0.20, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 50, confidence=0.40, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)

    assert result.engine == "paddleocr"
    assert result.text == "B" * 50
