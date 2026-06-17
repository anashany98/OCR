"""Tests for the PaddleOCR output-format drift (UPG-3).

The adapter must accept every output shape PaddleOCR has shipped over
the years AND be tolerant of formats we have not seen yet. These tests
pin that contract so a future PaddleOCR upgrade that introduces a new
shape (or returns a generator instead of a list) does not silently
regress the cascade.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.ocr.paddle_adapter import normalize_paddle_output


# ---------------------------------------------------------------------------
# Predict-style (PaddleOCR 3.x)
# ---------------------------------------------------------------------------


def test_predict_dict_with_polygon_as_ndarray():
    """``dt_polys`` may be a list of ``np.ndarray`` instead of plain lists."""

    class FakeArray:
        def tolist(self):
            return [[0, 0], [10, 0], [10, 10], [0, 10]]

    raw = {
        "rec_texts": ["Hi"],
        "rec_scores": [0.8],
        "dt_polys": [FakeArray()],
    }
    blocks = normalize_paddle_output(raw)
    assert len(blocks) == 1
    assert blocks[0].bbox == (0.0, 0.0, 10.0, 10.0)


def test_predict_dict_with_mismatched_lengths_does_not_crash():
    raw = {
        "rec_texts": ["A", "B", "C"],
        "rec_scores": [0.5],  # shorter
        "dt_polys": [],  # shorter
    }
    blocks = normalize_paddle_output(raw)
    assert [b.text for b in blocks] == ["A", "B", "C"]
    # Confidence falls back to None when the scores list is shorter.
    assert blocks[0].confidence == 0.5
    assert blocks[1].confidence is None
    assert blocks[2].confidence is None
    assert all(b.bbox is None for b in blocks)


# ---------------------------------------------------------------------------
# Legacy (PaddleOCR 2.x)
# ---------------------------------------------------------------------------


def test_legacy_payload_with_empty_payload_falls_back_to_str():
    """A ``payload`` that's not a 2-element list becomes ``str(payload)``."""
    polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
    raw = [[[polygon, ["only text"]]]]
    blocks = normalize_paddle_output(raw)
    assert len(blocks) == 1
    # payload is a list of length 1, so the adapter falls back to
    # ``str(payload)`` rather than reading ``payload[1]``.
    assert blocks[0].text == str(["only text"])
    assert blocks[0].confidence is None


def test_legacy_payload_with_scalar_payload():
    polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
    raw = [[[polygon, 42]]]
    blocks = normalize_paddle_output(raw)
    assert len(blocks) == 1
    assert blocks[0].text == "42"
    assert blocks[0].confidence is None


def test_legacy_line_as_pair_of_scalars_returns_none():
    """A line that doesn't fit the [polygon, payload] shape becomes
    a degenerate block with ``text = str(payload)`` and no bbox.

    The adapter does NOT silently drop the line: the cascade relies on
    every line producing a block (with whatever text the engine
    returned) so the admin UI can show the breakdown.
    """
    raw = [[[0, 0]]]
    blocks = normalize_paddle_output(raw)
    assert len(blocks) == 1
    assert blocks[0].text == "0"
    assert blocks[0].bbox is None


# ---------------------------------------------------------------------------
# Generator / iterable
# ---------------------------------------------------------------------------


def test_generator_input_is_consumed():
    def gen():
        yield {
            "rec_texts": ["G"],
            "rec_scores": [0.9],
            "dt_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
        }

    blocks = normalize_paddle_output(gen())
    assert len(blocks) == 1
    assert blocks[0].text == "G"


# ---------------------------------------------------------------------------
# Unknown shape strictness
# ---------------------------------------------------------------------------


def test_strict_mode_raises_on_unknown_page_type():
    raw = [123]  # page is an int
    with pytest.raises(ValueError):
        normalize_paddle_output(raw, allow_unknown=False)


def test_lenient_mode_returns_empty_on_unknown_page_type():
    raw = [123]
    assert normalize_paddle_output(raw, allow_unknown=True) == []


# ---------------------------------------------------------------------------
# Object-style (forward-compat)
# ---------------------------------------------------------------------------


def test_object_with_text_score_bbox_not_polygon():
    class Line:
        text = "Obj"
        score = 0.7
        bbox = [[0, 0], [5, 0], [5, 5], [0, 5]]  # polygon-shaped

    blocks = normalize_paddle_output([Line()])
    assert len(blocks) == 1
    assert blocks[0].text == "Obj"
    assert blocks[0].confidence == 0.7
    assert blocks[0].bbox == (0.0, 0.0, 5.0, 5.0)


def test_object_with_text_only_skipped():
    """An object with text but no score is not a valid PaddleOCR line."""

    class Line:
        text = "no score"

    blocks = normalize_paddle_output([Line()])
    assert blocks == []