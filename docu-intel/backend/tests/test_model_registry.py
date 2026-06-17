"""Tests for app.ocr.model_registry (UPG-2).

The registry is pure configuration — no PaddleOCR / PaddleX import at
all — so these tests do not need any mocking. They cover the four
behaviours an operator depends on:

* every shipped profile id is resolvable
* unknown ids fall back to the default with a WARNING
* ``resolve_ocr_models`` honours the ENV overrides
* ``resolve_structure_pipeline`` flips to the legacy profile when the
  operator forces the fallback
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.ocr.model_registry import (
    OcrProfile,
    StructureProfile,
    get_ocr_profile,
    get_structure_profile,
    list_ocr_profiles,
    list_structure_profiles,
    resolve_ocr_models,
    resolve_structure_pipeline,
)


# ---------------------------------------------------------------------------
# Profile catalogue
# ---------------------------------------------------------------------------


def test_ocr_profile_catalogue_is_complete():
    ids = {p.id for p in list_ocr_profiles()}
    assert ids == {
        "ppocr_v5_server",
        "ppocr_v6_tiny",
        "ppocr_v6_small",
        "ppocr_v6_medium",
        "custom",
    }


def test_structure_profile_catalogue_is_complete():
    ids = {p.id for p in list_structure_profiles()}
    assert ids == {
        "pp_structure_v3",
        "layout_parsing_legacy",
        "custom",
    }


def test_default_ocr_profile_is_ppocr_v6_medium():
    profile = get_ocr_profile(None)
    assert profile.id == "ppocr_v6_medium"
    assert profile.backend == "paddleocr"
    assert profile.model_type == "PP-OCRv6"
    assert profile.use_predict_api is True


def test_default_structure_profile_is_pp_structure_v3():
    profile = get_structure_profile(None)
    assert profile.id == "pp_structure_v3"
    assert profile.backend == "paddlex"
    assert profile.pipeline == "layout_parsing"
    assert profile.prefer_v3 is True


# ---------------------------------------------------------------------------
# Unknown id handling
# ---------------------------------------------------------------------------


def test_unknown_ocr_profile_falls_back_to_default(caplog):
    with caplog.at_level(logging.WARNING, logger="app.ocr.model_registry"):
        profile = get_ocr_profile("does_not_exist")
    assert profile.id == "ppocr_v6_medium"
    messages = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "unknown paddle_ocr_profile" in messages


def test_unknown_structure_profile_falls_back_to_default(caplog):
    with caplog.at_level(logging.WARNING, logger="app.ocr.model_registry"):
        profile = get_structure_profile("nope")
    assert profile.id == "pp_structure_v3"
    messages = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "unknown pp_structure_profile" in messages


def test_empty_string_treated_as_default():
    assert get_ocr_profile("").id == "ppocr_v6_medium"
    assert get_structure_profile("").id == "pp_structure_v3"


# ---------------------------------------------------------------------------
# resolve_ocr_models
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal duck-typed stand-in for ``app.core.config.settings``."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _settings(**overrides):
    base = dict(
        paddle_ocr_profile="ppocr_v6_medium",
        paddle_text_detection_model_name=None,
        paddle_text_recognition_model_name=None,
        paddle_use_predict_api=True,
        paddle_force_legacy_ocr_api=False,
        paddle_force_predict_api=False,
    )
    base.update(overrides)
    return _FakeSettings(**base)


def test_resolve_ocr_models_returns_named_profile():
    profile = resolve_ocr_models(_settings(paddle_ocr_profile="ppocr_v6_small"))
    assert profile.id == "ppocr_v6_small"
    assert profile.use_predict_api is True


def test_resolve_ocr_models_honours_detection_override():
    profile = resolve_ocr_models(
        _settings(paddle_ocr_profile="custom", paddle_text_detection_model_name="/models/det")
    )
    assert profile.id == "custom"
    assert profile.detection_model_name == "/models/det"


def test_resolve_ocr_models_honours_recognition_override():
    profile = resolve_ocr_models(
        _settings(paddle_ocr_profile="custom", paddle_text_recognition_model_name="/models/rec")
    )
    assert profile.recognition_model_name == "/models/rec"


def test_resolve_ocr_models_force_legacy_disables_predict():
    profile = resolve_ocr_models(
        _settings(paddle_use_predict_api=True, paddle_force_legacy_ocr_api=True)
    )
    assert profile.use_predict_api is False


def test_resolve_ocr_models_force_predict_enables_predict():
    profile = resolve_ocr_models(
        _settings(paddle_use_predict_api=False, paddle_force_predict_api=True)
    )
    assert profile.use_predict_api is True


# ---------------------------------------------------------------------------
# resolve_structure_pipeline
# ---------------------------------------------------------------------------


def _structure_settings(**overrides):
    base = dict(
        pp_structure_profile="pp_structure_v3",
        pp_structure_pipeline_name=None,
        pp_structure_use_v3=True,
        pp_structure_force_paddlex_fallback=False,
    )
    base.update(overrides)
    return _FakeSettings(**base)


def test_resolve_structure_pipeline_default_keeps_v3():
    profile = resolve_structure_pipeline(_structure_settings())
    assert profile.id == "pp_structure_v3"
    assert profile.prefer_v3 is True
    assert profile.pipeline == "layout_parsing"


def test_resolve_structure_pipeline_force_fallback_returns_legacy():
    profile = resolve_structure_pipeline(
        _structure_settings(pp_structure_force_paddlex_fallback=True)
    )
    assert profile.id == "layout_parsing_legacy"
    assert profile.prefer_v3 is False


def test_resolve_structure_pipeline_custom_honours_pipeline_name():
    profile = resolve_structure_pipeline(
        _structure_settings(
            pp_structure_profile="custom", pp_structure_pipeline_name="layout_parsing_v4"
        )
    )
    assert profile.id == "custom"
    assert profile.pipeline == "layout_parsing_v4"


def test_resolve_structure_pipeline_disabling_v3_keeps_canonical_profile():
    profile = resolve_structure_pipeline(_structure_settings(pp_structure_use_v3=False))
    assert profile.id == "pp_structure_v3"
    assert profile.prefer_v3 is False


def test_ocr_profile_is_immutable():
    profile = get_ocr_profile("ppocr_v6_medium")
    try:
        profile.id = "tampered"  # type: ignore[misc]
        raise AssertionError("expected frozen dataclass to reject assignment")
    except Exception:
        pass


def test_structure_profile_is_immutable():
    profile = get_structure_profile("pp_structure_v3")
    try:
        profile.id = "tampered"  # type: ignore[misc]
        raise AssertionError("expected frozen dataclass to reject assignment")
    except Exception:
        pass


def test_resolve_ocr_models_uses_settings_namespace():
    """The function must work with a plain SimpleNamespace (no pydantic)."""
    profile = resolve_ocr_models(SimpleNamespace(paddle_ocr_profile="ppocr_v6_tiny"))
    assert profile.id == "ppocr_v6_tiny"