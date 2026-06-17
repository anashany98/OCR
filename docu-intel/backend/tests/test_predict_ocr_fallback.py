"""Tests for the PaddleOCR predict / ocr fallback path (UPG-3).

The adapter must:

1. Prefer ``predict()`` when the engine exposes it.
2. Fall back to ``ocr()`` when ``predict`` is missing OR raises.
3. Honour ``paddle_force_legacy_ocr_api`` even when ``predict`` is fine.
4. Honour ``paddle_force_predict_api`` even when ``predict`` would
   normally be skipped (e.g. ``use_predict_api=False``).
5. Emit an empty ``OCRResult`` (no exception) when the engine has
   neither API — so the cascade can keep the primary tier.

The tests use a ``MagicMock`` engine factory so no real PaddleOCR is
imported.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ocr.model_registry import OcrProfile
from app.ocr.paddle_adapter import PaddleOCRAdapter


def _profile(use_predict: bool = True, force_legacy: bool = False, force_predict: bool = False) -> OcrProfile:
    return OcrProfile(
        id="ppocr_v6_medium",
        backend="paddleocr",
        model_type="PP-OCRv6",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=use_predict,
    )


def _engine(predict=None, ocr=None) -> SimpleNamespace:
    """Build a fake engine exposing only the requested APIs."""
    return SimpleNamespace(
        predict=predict or (lambda path: []),
        ocr=ocr or (lambda path: None),
    )


# ---------------------------------------------------------------------------
# Predict preferred
# ---------------------------------------------------------------------------


def test_predict_used_when_available(tmp_path: Path):
    calls = {"predict": 0, "ocr": 0}

    def predict(path):
        calls["predict"] += 1
        return [{"rec_texts": ["from predict"], "rec_scores": [0.9], "dt_polys": []}]

    def ocr(path):
        calls["ocr"] += 1
        return None

    engine = _engine(predict=predict, ocr=ocr)
    adapter = PaddleOCRAdapter(
        profile=_profile(use_predict=True),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == "from predict"
    assert calls["predict"] == 1
    assert calls["ocr"] == 0


def test_predict_failure_falls_back_to_ocr(tmp_path: Path):
    def broken_predict(path):
        raise RuntimeError("predict() not implemented in this PaddleOCR build")

    polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]

    def ocr(path):
        return [[[polygon, ["from ocr", 0.6]]]]

    engine = _engine(predict=broken_predict, ocr=ocr)
    adapter = PaddleOCRAdapter(
        profile=_profile(use_predict=True),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == "from ocr"


# ---------------------------------------------------------------------------
# Predict missing → ocr
# ---------------------------------------------------------------------------


def test_predict_missing_uses_ocr(tmp_path: Path):
    polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
    engine = SimpleNamespace(ocr=lambda path: [[[polygon, ["legacy", 0.5]]]])
    adapter = PaddleOCRAdapter(
        profile=_profile(use_predict=True),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == "legacy"


def test_predict_skipped_when_use_predict_false(tmp_path: Path):
    polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
    predict_calls = {"n": 0}

    def predict(path):
        predict_calls["n"] += 1
        return [{"rec_texts": ["should not run"], "rec_scores": [0.9], "dt_polys": []}]

    def ocr(path):
        return [[[polygon, ["ocr only", 0.5]]]]

    engine = _engine(predict=predict, ocr=ocr)
    adapter = PaddleOCRAdapter(
        profile=_profile(use_predict=False),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == "ocr only"
    assert predict_calls["n"] == 0


# ---------------------------------------------------------------------------
# Empty engine (no API at all)
# ---------------------------------------------------------------------------


def test_engine_with_no_apis_returns_empty(tmp_path: Path):
    engine = SimpleNamespace(name="noop")  # no predict, no ocr
    adapter = PaddleOCRAdapter(
        profile=_profile(),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == ""
    assert result.blocks == []
    assert result.confidence is None


def test_engine_predict_returns_none(tmp_path: Path):
    engine = _engine(predict=lambda path: None, ocr=lambda path: None)
    adapter = PaddleOCRAdapter(
        profile=_profile(),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == ""


def test_engine_predict_returns_empty_list(tmp_path: Path):
    engine = _engine(predict=lambda path: [], ocr=lambda path: None)
    adapter = PaddleOCRAdapter(
        profile=_profile(),
        lang="es",
        device="cpu",
        engine_factory=lambda: engine,
        log_runtime_info=False,
    )
    result = adapter.run(tmp_path / "img.png")
    assert result.text == ""


# ---------------------------------------------------------------------------
# Cascading integration: adapter failure does not crash the cascade
# ---------------------------------------------------------------------------


def test_adapter_init_failure_raises_runtimeerror():
    """When the engine factory raises, the adapter must surface the error
    so the cascade can keep the primary tier (Tesseract)."""

    def factory():
        raise RuntimeError("simulated init failure")

    adapter = PaddleOCRAdapter(
        profile=_profile(),
        lang="es",
        device="cpu",
        engine_factory=factory,
        log_runtime_info=False,
    )
    with pytest.raises(RuntimeError, match="simulated init failure"):
        adapter.run(Path("/tmp/img.png"))


def test_adapter_reuses_engine_across_calls(tmp_path: Path):
    """The adapter must instantiate the engine once and reuse it."""
    factory_calls = {"n": 0}

    def factory():
        factory_calls["n"] += 1
        return _engine(
            predict=lambda path: [{"rec_texts": ["x"], "rec_scores": [0.5], "dt_polys": []}]
        )

    adapter = PaddleOCRAdapter(
        profile=_profile(),
        lang="es",
        device="cpu",
        engine_factory=factory,
        log_runtime_info=False,
    )
    adapter.run(tmp_path / "a.png")
    adapter.run(tmp_path / "b.png")
    adapter.run(tmp_path / "c.png")
    assert factory_calls["n"] == 1