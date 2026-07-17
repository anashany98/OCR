"""Factory topology tests that do not require Tesseract or a GPU."""

from __future__ import annotations

import sys
from types import ModuleType

from app.core.config import settings
from app.ocr import factory
from app.ocr.tier4_chain import Tier4EngineChain


class _Tesseract:
    name = "tesseract"

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def _patch_classical_modules(monkeypatch) -> None:
    tesseract_module = ModuleType("app.ocr.tesseract")
    tesseract_module.TesseractOCREngine = _Tesseract
    paddle_module = ModuleType("app.ocr.paddle")
    paddle_module.PaddleOCREngine = object
    paddle_module._get_gpu_device = lambda: None
    paddle_module.gpu_has_headroom = lambda: False
    monkeypatch.setitem(sys.modules, "app.ocr.tesseract", tesseract_module)
    monkeypatch.setitem(sys.modules, "app.ocr.paddle", paddle_module)


def test_factory_preserves_old_topology_when_ovis_is_disabled(monkeypatch):
    _patch_classical_modules(monkeypatch)
    monkeypatch.setattr(settings, "paddleocr_gpu_only", True)
    monkeypatch.setattr(settings, "enable_dots_mocr", False)
    monkeypatch.setattr(settings, "nuextract_enabled", False)
    monkeypatch.setattr(settings, "ovisocr2_enabled", False)

    cascade = factory._build_cascading_engine()

    assert cascade.vlm_ocr is None
    assert cascade.tier4_fallback is None


def test_factory_adds_ovis_chain_only_when_feature_is_enabled(monkeypatch):
    _patch_classical_modules(monkeypatch)
    monkeypatch.setattr(settings, "paddleocr_gpu_only", True)
    monkeypatch.setattr(settings, "enable_dots_mocr", False)
    monkeypatch.setattr(settings, "nuextract_enabled", False)
    monkeypatch.setattr(settings, "ovisocr2_enabled", True)

    cascade = factory._build_cascading_engine()

    assert isinstance(cascade.vlm_ocr, Tier4EngineChain)
    assert [engine.name for engine in cascade.vlm_ocr.engines] == ["ovisocr2"]
