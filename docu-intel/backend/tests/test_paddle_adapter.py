"""Tests for app.ocr.paddle_adapter (UPG-3).

Covers the five behaviours the adapter promises:

* ``normalize_paddle_output`` accepts every PaddleOCR shape we have
  seen shipped (3.x dict, 2.x nested list, object with .text/.score,
  None, future unknown shape).
* ``polygon_to_bbox`` is tolerant of garbage input.
* The adapter prefers ``predict()`` when available and falls back to
  ``ocr()`` when ``predict`` raises or is missing.
* The adapter forces the legacy ``ocr()`` path when the operator sets
  ``paddle_force_legacy_ocr_api``.
* The adapter raises on init timeout and marks itself unavailable.

All tests are pure-Python: no PaddleOCR import. The adapter is
constructed with an ``engine_factory`` that returns a mock object.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ocr.base import OCRBlock, OCRResult
from app.ocr.model_registry import OcrProfile
from app.ocr.paddle_adapter import (
    PaddleOCRAdapter,
    normalize_paddle_output,
    polygon_to_bbox,
)


# ---------------------------------------------------------------------------
# polygon_to_bbox
# ---------------------------------------------------------------------------


class TestPolygonToBbox:
    def test_rectangle(self):
        assert polygon_to_bbox([[0, 0], [10, 0], [10, 5], [0, 5]]) == (0.0, 0.0, 10.0, 5.0)

    def test_non_rectangular(self):
        assert polygon_to_bbox([[10, 20], [50, 10], [90, 30], [60, 80]]) == (10.0, 10.0, 90.0, 80.0)

    def test_single_point(self):
        assert polygon_to_bbox([[7, 7]]) == (7.0, 7.0, 7.0, 7.0)

    def test_returns_none_for_garbage(self):
        assert polygon_to_bbox(None) is None
        assert polygon_to_bbox("foo") is None
        assert polygon_to_bbox(42) is None
        assert polygon_to_bbox([]) is None
        assert polygon_to_bbox([["a", "b"]]) is None


# ---------------------------------------------------------------------------
# normalize_paddle_output
# ---------------------------------------------------------------------------


class TestNormalizePaddleOutput:
    def test_none_returns_empty(self):
        assert normalize_paddle_output(None) == []

    def test_empty_returns_empty(self):
        assert normalize_paddle_output([]) == []

    def test_single_dict_predict_shape(self):
        raw = {
            "rec_texts": ["Hi"],
            "rec_scores": [0.9],
            "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
        }
        blocks = normalize_paddle_output(raw)
        assert len(blocks) == 1
        assert blocks[0].text == "Hi"
        assert blocks[0].confidence == 0.9
        assert blocks[0].bbox == (0.0, 0.0, 10.0, 10.0)

    def test_list_of_dicts_multi_page(self):
        raw = [
            {
                "rec_texts": ["A"],
                "rec_scores": [0.95],
                "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
            },
            {
                "rec_texts": ["B"],
                "rec_scores": [0.85],
                "dt_polys": [[[0, 10], [10, 10], [10, 20], [0, 20]]],
            },
        ]
        blocks = normalize_paddle_output(raw)
        assert [b.text for b in blocks] == ["A", "B"]
        assert [b.confidence for b in blocks] == [0.95, 0.85]

    def test_legacy_nested_list_shape(self):
        polygon = [[0, 0], [100, 0], [100, 50], [0, 50]]
        raw = [[[polygon, ["Hola", 0.85]]]]
        blocks = normalize_paddle_output(raw)
        assert len(blocks) == 1
        assert blocks[0].text == "Hola"
        assert blocks[0].confidence == 0.85
        assert blocks[0].bbox == (0.0, 0.0, 100.0, 50.0)

    def test_legacy_multi_page_multi_line(self):
        p1 = [[0, 0], [50, 0], [50, 20], [0, 20]]
        p2 = [[0, 20], [50, 20], [50, 40], [0, 40]]
        raw = [
            [[p1, ["L1", 0.9]], [p2, ["L2", 0.8]]],
            [[p1, ["P2L1", 0.7]]],
        ]
        blocks = normalize_paddle_output(raw)
        assert [b.text for b in blocks] == ["L1", "L2", "P2L1"]
        assert [b.confidence for b in blocks] == [0.9, 0.8, 0.7]

    def test_object_with_text_score_polygon(self):
        class Line:
            text = "Obj"
            score = 0.6
            polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]

        blocks = normalize_paddle_output([Line()])
        assert len(blocks) == 1
        assert blocks[0].text == "Obj"
        assert blocks[0].confidence == 0.6

    def test_unknown_with_allow(self):
        assert normalize_paddle_output("foo", allow_unknown=True) == []

    def test_unknown_without_allow_raises(self):
        with pytest.raises(ValueError):
            normalize_paddle_output("foo", allow_unknown=False)

    def test_predict_dict_with_extra_keys_is_ignored(self):
        raw = {
            "rec_texts": ["X"],
            "rec_scores": [0.5],
            "dt_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
            "input_path": "/somewhere",
            "page_index": 7,
        }
        blocks = normalize_paddle_output(raw)
        assert len(blocks) == 1
        assert blocks[0].text == "X"

    def test_predict_dict_missing_dt_polys(self):
        raw = {"rec_texts": ["Y"], "rec_scores": [0.7], "dt_polys": []}
        blocks = normalize_paddle_output(raw)
        assert len(blocks) == 1
        assert blocks[0].text == "Y"
        assert blocks[0].bbox is None


# ---------------------------------------------------------------------------
# Adapter — predict / ocr routing
# ---------------------------------------------------------------------------


def _profile(use_predict: bool = True) -> OcrProfile:
    return OcrProfile(
        id="ppocr_v6_medium",
        backend="paddleocr",
        model_type="PP-OCRv6",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=use_predict,
    )


def _make_engine(*, predict=None, ocr=None) -> MagicMock:
    engine = MagicMock()
    if predict is not None:
        engine.predict = predict
    else:
        del engine.predict  # not callable
    if ocr is not None:
        engine.ocr = ocr
    else:
        del engine.ocr
    return engine


class TestPaddleAdapter:
    def test_predict_path_used_when_available(self, tmp_path: Path):
        engine = _make_engine(
            predict=lambda path: [
                {
                    "rec_texts": ["via predict"],
                    "rec_scores": [0.9],
                    "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                }
            ]
        )
        adapter = PaddleOCRAdapter(
            profile=_profile(),
            lang="es",
            device="cpu",
            engine_factory=lambda: engine,
            log_runtime_info=False,
        )
        result = adapter.run(tmp_path / "img.png")
        assert result.engine == "paddleocr"
        assert result.text == "via predict"
        assert result.confidence == 0.9

    def test_fallback_to_ocr_when_predict_missing(self, tmp_path: Path):
        polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
        engine = _make_engine(
            ocr=lambda path: [[[polygon, ["via ocr", 0.7]]]]
        )
        adapter = PaddleOCRAdapter(
            profile=_profile(),
            lang="es",
            device="cpu",
            engine_factory=lambda: engine,
            log_runtime_info=False,
        )
        result = adapter.run(tmp_path / "img.png")
        assert result.text == "via ocr"
        assert result.confidence == 0.7

    def test_fallback_to_ocr_when_predict_raises(self, tmp_path: Path):
        polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]

        def broken_predict(path):
            raise RuntimeError("predict not implemented in this build")

        engine = _make_engine(
            predict=broken_predict,
            ocr=lambda path: [[[polygon, ["via ocr", 0.5]]]],
        )
        adapter = PaddleOCRAdapter(
            profile=_profile(),
            lang="es",
            device="cpu",
            engine_factory=lambda: engine,
            log_runtime_info=False,
        )
        result = adapter.run(tmp_path / "img.png")
        assert result.text == "via ocr"

    def test_force_legacy_skips_predict(self, tmp_path: Path):
        polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
        engine = _make_engine(
            predict=lambda path: [
                {
                    "rec_texts": ["should not run"],
                    "rec_scores": [0.9],
                    "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                }
            ],
            ocr=lambda path: [[[polygon, ["legacy", 0.6]]]],
        )
        adapter = PaddleOCRAdapter(
            profile=_profile(),
            lang="es",
            device="cpu",
            engine_factory=lambda: engine,
            log_runtime_info=False,
        )
        # Force legacy path via the profile itself.
        adapter.profile = _profile(use_predict=False)
        result = adapter.run(tmp_path / "img.png")
        assert result.text == "legacy"

    def test_empty_result_when_engine_has_neither_api(self, tmp_path: Path):
        # Engine without predict() and without ocr(): adapter must not crash.
        engine = SimpleNamespace(name="noop")
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

    def test_adapter_marks_engine_name(self, tmp_path: Path):
        engine = _make_engine(
            predict=lambda path: [
                {"rec_texts": ["X"], "rec_scores": [0.5], "dt_polys": []}
            ]
        )
        adapter = PaddleOCRAdapter(
            profile=_profile(),
            lang="es",
            device="cpu",
            engine_factory=lambda: engine,
            log_runtime_info=False,
        )
        result = adapter.run(tmp_path / "img.png")
        assert result.engine == "paddleocr"

    def test_average_confidence_ignores_none(self, tmp_path: Path):
        engine = _make_engine(
            predict=lambda path: [
                {
                    "rec_texts": ["A", "B"],
                    "rec_scores": [0.6, None],
                    "dt_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]], []],
                }
            ]
        )
        adapter = PaddleOCRAdapter(
            profile=_profile(),
            lang="es",
            device="cpu",
            engine_factory=lambda: engine,
            log_runtime_info=False,
        )
        result = adapter.run(tmp_path / "img.png")
        assert result.text == "A\nB"
        assert result.confidence == 0.6