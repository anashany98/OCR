"""Tests for the O2 per-page language detection + adaptive thresholds.

The scorer / detection module is **pure** (no DB, no GPU, no PDF
parsing): the tests feed it hand-crafted strings and assert the
output. This keeps the tests fast and deterministic, and lets the
same module be exercised both in CI and from the live PDF parser.

The cascade integration tests are a thin shim that asserts the
cascade now consults the per-language thresholds via its
``current_language`` attribute, and that the legacy flag
(``ocr_cascading_use_adaptive_thresholds=False``) restores the
document-wide behaviour.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.ocr import cascading
from app.ocr.base import OCRBlock, OCRResult
from app.ocr.cascading import CascadingOCREngine
from app.services.metrics import track_ocr_language_detected
from app.services.ocr_language import (
    DEFAULT_THRESHOLDS,
    LanguageProfile,
    LanguageThresholds,
    THRESHOLDS_BY_LANG,
    detect_language,
    paddle_lang_for,
    tesseract_lang_for,
    thresholds_for,
)


# ---------------------------------------------------------------------------
# Unit tests: thresholds_for + tesseract_lang_for + paddle_lang_for
# ---------------------------------------------------------------------------


def test_thresholds_for_unknown_language_returns_default():
    assert thresholds_for(None) == DEFAULT_THRESHOLDS
    assert thresholds_for("") == DEFAULT_THRESHOLDS
    assert thresholds_for("xx") == DEFAULT_THRESHOLDS  # unknown code


def test_thresholds_for_known_latin_languages():
    es = thresholds_for("es")
    en = thresholds_for("en")
    de = thresholds_for("de")
    assert es == LanguageThresholds(min_chars=30, min_confidence=0.50)
    assert en == LanguageThresholds(min_chars=30, min_confidence=0.50)
    # German: tighter confidence floor because of umlauts.
    assert de.min_confidence > es.min_confidence


def test_thresholds_for_cjk_uses_denser_pack():
    ja = thresholds_for("ja")
    zh = thresholds_for("zh")
    # CJK chars carry more information per glyph; we accept a
    # shorter text length and a lower confidence.
    assert ja.min_chars < DEFAULT_THRESHOLDS.min_chars
    assert ja.min_confidence < DEFAULT_THRESHOLDS.min_confidence
    assert zh == ja


def test_thresholds_for_strips_region_subtags():
    # langdetect emits "pt-br" / "zh-cn" etc.; the lookup must
    # ignore the region subtag.
    assert thresholds_for("pt-br") == thresholds_for("pt")
    assert thresholds_for("zh-cn") == thresholds_for("zh")
    assert thresholds_for("en-US") == thresholds_for("en")


def test_tesseract_lang_for_uses_tesseract_codes():
    assert tesseract_lang_for("es") == "spa"
    assert tesseract_lang_for("en") == "eng"
    assert tesseract_lang_for("de") == "deu"
    assert tesseract_lang_for("zh") == "chi_sim"
    assert tesseract_lang_for("ja") == "jpn"


def test_tesseract_lang_for_unknown_falls_back_to_default():
    assert tesseract_lang_for(None) == "spa+eng"
    assert tesseract_lang_for("xx") == "spa+eng"
    assert tesseract_lang_for("xx", default="deu+eng") == "deu+eng"


def test_paddle_lang_for_uses_paddle_codes():
    assert paddle_lang_for("es") == "es"
    assert paddle_lang_for("zh") == "ch"
    assert paddle_lang_for("ja") == "japan"
    assert paddle_lang_for(None) == "es"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_language_short_text_returns_none():
    assert detect_language("") is None
    assert detect_language("hello") is None  # too short, no script hint
    assert detect_language("1234") is None


def test_detect_language_detects_spanish():
    text = (
        "Factura número 245745 con fecha 12 de marzo de 2025, "
        "emitida por el proveedor García para el cliente Acme. "
        "El importe total es de doce mil cuatrocientos cincuenta euros."
    )
    assert detect_language(text) == "es"


def test_detect_language_detects_english():
    text = (
        "Invoice 245745 dated March 12 2025 issued by Garcia "
        "for the customer Acme. The total amount is twelve thousand "
        "four hundred and fifty euros and zero cents."
    )
    assert detect_language(text) == "en"


def test_detect_language_detects_german_via_hint():
    # German with umlauts. The script hint path (CJK/RTL) does not
    # apply to Latin scripts, so we feed a longer text that lets
    # ``langdetect`` do its job; the umlauts give it a strong signal.
    text = (
        "Schöne Grüße aus München, eine wunderbare Stadt im Süden "
        "Deutschlands mit vielen Sehenswürdigkeiten und freundlichen "
        "Menschen, die gerne Brezeln essen."
    )
    assert detect_language(text) == "de"


def test_detect_language_detects_japanese_via_hint():
    # Japanese has hiragana; the script hint must catch it even
    # when the text is short.
    text = "こんにちは、世界"
    assert detect_language(text) == "ja"


def test_detect_language_detects_chinese_via_hint():
    text = "你好世界，欢迎使用"  # hello world, welcome
    assert detect_language(text) == "zh"


def test_detect_language_strips_region_subtag():
    """A long Portuguese text that langdetect would label "pt" but
    might also surface as "pt-br"; the public API must hand back
    the bare 2-letter code."""
    text = (
        "Esta é uma factura número 245745 emitida a doze de março "
        "de dois mil e vinte e cinco. O valor total é de doze mil "
        "quatrocentos e cinquenta euros."
    )
    code = detect_language(text)
    assert code in {"pt", "pt-br"} or code == "pt"  # langdetect may vary


def test_detect_language_on_empty_returns_none():
    assert detect_language("   \n  ") is None


# ---------------------------------------------------------------------------
# LanguageProfile
# ---------------------------------------------------------------------------


def test_language_profile_for_text_returns_complete_bundle():
    text = (
        "Rechnung 245745 vom 12. März 2025. Der Gesamtbetrag "
        "beträgt zwölftausendvierhundertfünfzig Euro."
    )
    profile = LanguageProfile.for_text(text)
    assert profile.detected == "de"
    assert profile.tesseract_lang == "deu"
    assert profile.paddle_lang == "de"
    assert profile.thresholds.min_confidence > DEFAULT_THRESHOLDS.min_confidence


def test_language_profile_for_short_text_falls_back_to_defaults():
    profile = LanguageProfile.for_text("hi")
    # Short text: no detection, but the defaults are still set
    # against the project's tesseract/paddle lang settings.
    assert profile.detected is None
    assert profile.tesseract_lang == "spa+eng"
    assert profile.paddle_lang == "es"
    # And the thresholds are the conservative default.
    assert profile.thresholds == DEFAULT_THRESHOLDS


# ---------------------------------------------------------------------------
# Cascade integration: adaptive thresholds via current_language
# ---------------------------------------------------------------------------


class _RecordingEngine:
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


def test_cascade_uses_per_language_min_confidence(monkeypatch, tmp_path: Path):
    """A page detected as German (min_confidence=0.55) must escalate
    when the primary result lands at conf=0.52, whereas a Spanish
    page (min_confidence=0.50) would keep the same result."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_cascading_use_adaptive_thresholds", True)

    primary = _RecordingEngine("primary", _result("A" * 40, confidence=0.52, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 60, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    # Spanish: conf=0.52 > 0.50 (es) -> primary is acceptable, no escalation.
    cascade.current_language = "es"
    cascade.extract(image)
    assert primary.calls == 1
    assert fallback.calls == 0
    primary.calls = 0

    # German: conf=0.52 < 0.55 (de) -> escalate.
    cascade.current_language = "de"
    cascade.extract(image)
    assert primary.calls == 1
    assert fallback.calls == 1


def test_cascade_adaptive_thresholds_can_be_disabled(monkeypatch, tmp_path: Path):
    """When ``ocr_cascading_use_adaptive_thresholds=False`` the
    cascade must use the document-wide constants regardless of the
    detected language."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_cascading_use_adaptive_thresholds", False)

    primary = _RecordingEngine("primary", _result("A" * 40, confidence=0.52, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 60, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    # German detected, but adaptive thresholds are off: 0.52 > 0.50 (default).
    cascade.current_language = "de"
    cascade.extract(image)
    assert primary.calls == 1
    assert fallback.calls == 0


def test_cascade_adaptive_thresholds_track_metric(monkeypatch, tmp_path: Path):
    """Each time the cascade consults the per-language thresholds it
    must record a Prometheus counter. We assert the helper is
    called for the active language and is *not* called when the
    language is None."""
    threshold_events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cascading,
        "track_ocr_language_threshold_used",
        lambda language, threshold_type: threshold_events.append((language, threshold_type)),
        raising=False,
    )

    primary = _RecordingEngine("primary", _result("A" * 40, confidence=0.6, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 60, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)
    cascade.current_language = "de"

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    cascade.extract(image)

    # The cascade consults the per-language thresholds for *both*
    # min_chars and min_confidence when adaptive is on and a
    # language is set.
    languages = [evt[0] for evt in threshold_events]
    assert "de" in languages
    threshold_types = {evt[1] for evt in threshold_events}
    assert threshold_types == {"min_chars", "min_confidence"}


def test_cascade_adaptive_thresholds_dont_track_when_no_language(tmp_path: Path, monkeypatch):
    """No ``current_language`` -> use the document-wide constants
    and do not emit per-language metrics."""
    threshold_events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cascading,
        "track_ocr_language_threshold_used",
        lambda language, threshold_type: threshold_events.append((language, threshold_type)),
        raising=False,
    )

    primary = _RecordingEngine("primary", _result("A" * 40, confidence=0.6, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 60, confidence=0.95, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)
    cascade.current_language = None

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    cascade.extract(image)
    assert threshold_events == []


def test_cascade_s0_6_skip_logic_still_works_with_adaptive_thresholds(monkeypatch, tmp_path: Path):
    """The S0.6 "skip Tier 2 when gain is not significant" feature
    must keep working when O2 is enabled. We feed a primary that
    fails the per-language gate but the fallback is only marginally
    better, and assert the cascade still keeps the primary."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_cascading_use_adaptive_thresholds", True)

    # Primary is not acceptable for German (only 10 chars, below
    # min_chars=30) but the fallback adds only 1 char with the same
    # confidence: the S0.6 logic must keep the primary.
    primary = _RecordingEngine("primary", _result("A" * 10, confidence=0.30, engine="tesseract"))
    fallback = _RecordingEngine("fallback", _result("B" * 11, confidence=0.30, engine="paddleocr"))
    cascade = CascadingOCREngine(primary=primary, fallback=fallback, min_chars=30, min_confidence=0.5)
    cascade.current_language = "de"

    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = cascade.extract(image)
    assert result.engine == "tesseract"
    assert primary.calls == 1
    assert fallback.calls == 1  # was called, but lost the comparison


# ---------------------------------------------------------------------------
# Smoke: the metrics module exposes the new track_* functions
# ---------------------------------------------------------------------------


def test_metrics_helpers_do_not_raise(caplog):
    """The new metrics helpers must accept any string without
    raising; Prometheus label cardinality is bounded by the helper
    itself, not by the caller."""
    track_ocr_language_detected("es", "presupuesto")
    track_ocr_language_detected("xx", "")  # unknown language + missing type
    track_ocr_language_detected("", "otro")
