"""Tests for the PPStructureEngine and the 3-tier cascade.

These tests are unit-level: they don't load the real PaddleX pipeline
(that's gated behind a slow integration test). They exercise the
engine's CPU-refusal guard, the result-shape conversion, and the
cascade's Tier-3 escalation logic with fake engines.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ocr.base import OCRBlock, OCRResult
from app.ocr.cascading import CascadingOCREngine
from app.ocr.factory import get_ocr_engine_class
from app.ocr.pp_structure import PPStructureEngine


# ---------------------------------------------------------------------------
# Engine guards
# ---------------------------------------------------------------------------


def test_pp_structure_engine_refuses_cpu():
    """Tier 3 is GPU-only. PaddlePaddle 3.3.x crashes layout_parsing on
    CPU with ConvertPirAttribute2RuntimeAttribute, so the engine must
    fail fast at construction rather than at first extract()."""
    with pytest.raises(RuntimeError, match="GPU-only"):
        PPStructureEngine(device="cpu")


def test_pp_structure_engine_accepts_gpu():
    eng = PPStructureEngine(device="gpu", lang="es")
    assert eng.device == "gpu"
    assert eng.lang == "es"
    assert eng.name == "pp_structure"


# ---------------------------------------------------------------------------
# Result-shape conversion (no real model — we test the converter via a stub)
# ---------------------------------------------------------------------------


def test_pp_structure_extract_handles_empty_results(monkeypatch, tmp_path: Path):
    """When PaddleX returns no results, we still produce a valid
    OCRResult with engine='pp_structure'."""
    eng = PPStructureEngine(device="gpu")

    class _StubPipeline:
        def predict(self, _path):
            return iter([])  # empty generator

    monkeypatch.setattr(eng, "_pipeline", _StubPipeline())
    image = tmp_path / "blank.png"
    image.write_bytes(b"")

    result = eng.extract(image)

    assert result.engine == "pp_structure"
    assert result.text == ""
    assert result.blocks == []
    assert result.confidence is None


def test_pp_structure_extract_converts_parsing_res_list(monkeypatch, tmp_path: Path):
    """The converter should turn PaddleX's ``parsing_res_list`` into
    ``OCRBlock`` rows carrying ``block_type`` and bbox."""
    eng = PPStructureEngine(device="gpu")

    class _StubResult:
        def __init__(self, data):
            self._data = data

        @property
        def json(self):
            return {"res": self._data}

    class _StubPipeline:
        def predict(self, _path):
            return iter(
                [
                    _StubResult(
                        {
                            "parsing_res_list": [
                                {
                                    "block_bbox": [10.0, 20.0, 200.0, 60.0],
                                    "block_label": "doc_title",
                                    "block_content": "Factura 12345",
                                },
                                {
                                    "block_bbox": [10.0, 80.0, 200.0, 110.0],
                                    "block_label": "text",
                                    "block_content": "Total: 100,00 euros",
                                },
                                {
                                    "block_bbox": [10.0, 140.0, 200.0, 180.0],
                                    "block_label": "table",
                                    "block_content": "<table>...</table>",
                                },
                                {
                                    "block_bbox": [10.0, 210.0, 200.0, 260.0],
                                    "block_label": "figure",
                                    "block_content": "",  # empty — should be skipped
                                },
                            ],
                            "overall_ocr_res": {"rec_scores": [0.9, 0.8, 0.95]},
                        }
                    )
                ]
            )

    monkeypatch.setattr(eng, "_pipeline", _StubPipeline())
    image = tmp_path / "doc.png"
    image.write_bytes(b"")

    result = eng.extract(image)

    assert result.engine == "pp_structure"
    assert result.text == "Factura 12345\nTotal: 100,00 euros\n<table>...</table>"
    assert result.confidence == pytest.approx((0.9 + 0.8 + 0.95) / 3)
    assert len(result.blocks) == 3  # empty figure content dropped
    assert result.blocks[0].block_type == "doc_title"
    assert result.blocks[1].block_type == "text"
    assert result.blocks[2].block_type == "table"
    assert result.blocks[0].bbox == (10.0, 20.0, 200.0, 60.0)
    assert result.blocks[0].text == "Factura 12345"


# ---------------------------------------------------------------------------
# 3-tier cascade escalation
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Records calls and returns a canned OCRResult."""

    def __init__(self, name: str, result: OCRResult) -> None:
        self.name = name
        self._result = result
        self.calls = 0

    def extract(self, image_path: Path) -> OCRResult:
        self.calls += 1
        return self._result


def _result(text: str, confidence: float | None = 0.7, engine: str = "fake") -> OCRResult:
    return OCRResult(
        text=text,
        confidence=confidence,
        blocks=[OCRBlock(text=text, confidence=confidence, bbox=None, block_type=None)],
        engine=engine,
    )


def test_cascade_3tier_never_calls_pp_structure_when_tier2_wins(tmp_path: Path):
    """If Tier 2 produces an acceptable result, Tier 3 must not run."""
    pp = _FakeEngine("pp_structure", _result("Z" * 100, engine="pp_structure"))
    cascade = CascadingOCREngine(
        primary=_FakeEngine("tesseract", _result("x", engine="tesseract")),
        fallback=_FakeEngine("paddleocr", _result("Y" * 100, confidence=0.9, engine="paddleocr")),
        pp_structure=pp,
        min_chars=30,
        min_confidence=0.5,
    )

    result = cascade.extract(tmp_path / "x.png")

    assert result.engine == "paddleocr"
    assert pp.calls == 0  # Tier 3 skipped


def test_cascade_3tier_escalates_when_tier2_does_not_beat_tier1(tmp_path: Path):
    """When Tier 1 and Tier 2 both fail, Tier 3 fires."""
    pp = _FakeEngine("pp_structure", _result("Z" * 200, engine="pp_structure"))
    cascade = CascadingOCREngine(
        primary=_FakeEngine("tesseract", _result("x", engine="tesseract")),
        fallback=_FakeEngine("paddleocr", _result("Y" * 5, engine="paddleocr")),
        pp_structure=pp,
        min_chars=30,
        min_confidence=0.5,
    )

    result = cascade.extract(tmp_path / "x.png")

    assert result.engine == "pp_structure"
    assert pp.calls == 1


def test_cascade_3tier_keeps_best_when_pp_structure_returns_less_text(tmp_path: Path):
    """Tier 3 must not replace a better Tier 1 / Tier 2 result."""
    pp = _FakeEngine("pp_structure", _result("Z" * 10, engine="pp_structure"))
    cascade = CascadingOCREngine(
        primary=_FakeEngine("tesseract", _result("X" * 10, engine="tesseract")),  # unacceptable
        fallback=_FakeEngine("paddleocr", _result("Y" * 5, engine="paddleocr")),  # worse
        pp_structure=pp,
        min_chars=30,
        min_confidence=0.5,
    )

    result = cascade.extract(tmp_path / "x.png")

    # Tier 3 produced only 10 chars < 30 → must be rejected.
    assert result.engine == "tesseract"
    assert pp.calls == 1  # was called, but lost


def test_cascade_3tier_falls_back_silently_when_pp_structure_raises(tmp_path: Path):
    """If Tier 3 blows up (e.g. GPU OOM), the cascade returns the
    best of Tier 1 / Tier 2 and never propagates the error."""
    class _BoomEngine(_FakeEngine):
        def extract(self, image_path: Path) -> OCRResult:
            super().extract(image_path)
            raise RuntimeError("GPU OOM")

    pp = _BoomEngine("pp_structure", _result("ignored", engine="pp_structure"))
    cascade = CascadingOCREngine(
        primary=_FakeEngine("tesseract", _result("X" * 50, engine="tesseract")),
        fallback=_FakeEngine("paddleocr", _result("Y" * 5, engine="paddleocr")),
        pp_structure=pp,
        min_chars=30,
        min_confidence=0.5,
    )

    result = cascade.extract(tmp_path / "x.png")
    assert result.engine == "tesseract"


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_factory_standalone_pp_structure(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_engine", "pp_structure")
    get_ocr_engine_class.cache_clear()
    try:
        cls = get_ocr_engine_class()
        assert cls is PPStructureEngine
    finally:
        get_ocr_engine_class.cache_clear()


def test_factory_cascading_without_pp_structure(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_engine", "cascading")
    monkeypatch.setattr(settings, "ocr_cascading_use_pp_structure", False)
    get_ocr_engine_class.cache_clear()
    try:
        cls = get_ocr_engine_class()
        instance = cls()
        assert instance.pp_structure is None
    finally:
        get_ocr_engine_class.cache_clear()


def test_factory_cascading_with_pp_structure(monkeypatch):
    """When ``ocr_cascading_use_pp_structure`` is on, the factory wires
    ``pp_structure`` into the cascade. On GPU containers the engine
    instantiates fine; on CPU it raises ``RuntimeError("GPU-only")``
    which is the cascade's fail-fast guard."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_engine", "cascading")
    monkeypatch.setattr(settings, "ocr_cascading_use_pp_structure", True)
    get_ocr_engine_class.cache_clear()
    try:
        cls = get_ocr_engine_class()
        try:
            instance = cls()
        except RuntimeError as exc:
            # CPU environment: PPStructureEngine refused to instantiate.
            assert "GPU-only" in str(exc)
            return
        # GPU environment: pp_structure is wired in.
        from app.ocr.pp_structure import PPStructureEngine

        assert isinstance(instance.pp_structure, PPStructureEngine)
        assert instance.pp_structure.device == "gpu"
    finally:
        get_ocr_engine_class.cache_clear()
