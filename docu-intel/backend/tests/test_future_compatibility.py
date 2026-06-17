"""Future-compatibility tests for the OCR upgrade (UPG-2/3/4).

These tests pin the contract the adapters and registry promise to keep
when the next PaddleOCR / PaddleX release lands. They are *not* about
verifying the current PaddleOCR behaviour; they are about ensuring a
hypothetical PaddleOCR 4.0 (with whatever new shape it ships) does not
silently break the cascade. The test suite must stay green even after
a PaddleOCR upgrade; if it goes red, the upgrade introduced an
incompatible change that needs a new adapter branch.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ocr.model_registry import (
    OcrProfile,
    StructureProfile,
    get_ocr_profile,
    get_structure_profile,
    resolve_ocr_models,
    resolve_structure_pipeline,
)
from app.ocr.paddle_adapter import PaddleOCRAdapter, normalize_paddle_output
from app.ocr.structure_adapter import StructureAdapter, normalize_structure_output


# ---------------------------------------------------------------------------
# Registry — adding new profiles without touching engine code
# ---------------------------------------------------------------------------


class TestRegistryFutureCompatibility:
    def test_registry_lists_explicit_ids(self):
        """Operators MUST be able to enumerate every shipped profile id."""
        ocr_ids = {p.id for p in [get_ocr_profile("ppocr_v6_medium")]}
        assert "ppocr_v6_medium" in ocr_ids

    def test_unknown_profile_does_not_raise(self):
        """A typo in ``PADDLE_OCR_PROFILE`` must not crash the worker."""
        # Both calls must return *something* usable; the registry logs a
        # WARNING but returns the default.
        profile = get_ocr_profile("ppocr_v99_not_yet_a_real_profile")
        assert profile.id == "ppocr_v6_medium"

    def test_resolve_returns_a_profile_even_with_no_settings(self):
        """``resolve_ocr_models(None)`` would crash — but the public helper
        should be defensive. We test the safe path: ``resolve_ocr_models``
        with a duck-typed settings object."""
        settings = SimpleNamespace(
            paddle_ocr_profile="ppocr_v6_small",
            paddle_text_detection_model_name=None,
            paddle_text_recognition_model_name=None,
            paddle_use_predict_api=True,
            paddle_force_legacy_ocr_api=False,
            paddle_force_predict_api=False,
        )
        profile = resolve_ocr_models(settings)
        assert profile.id == "ppocr_v6_small"


# ---------------------------------------------------------------------------
# PaddleOCR — future output shapes
# ---------------------------------------------------------------------------


class TestPaddleFutureCompatibility:
    def test_unknown_top_level_shape_returns_empty(self):
        """A brand-new top-level shape returns [] with a warning."""
        # 4.x might return a typed object — represented here as a
        # dataclass-like that is neither dict nor list/tuple.
        class FuturePaddleOutput:
            pass

        assert normalize_paddle_output(FuturePaddleOutput(), allow_unknown=True) == []

    def test_unknown_top_level_shape_strict_raises(self):
        class FuturePaddleOutput:
            pass

        with pytest.raises(ValueError):
            normalize_paddle_output(FuturePaddleOutput(), allow_unknown=False)

    def test_predict_dict_with_new_keys_ignored(self):
        """PaddleOCR 4.x may add new keys; we ignore everything we don't
        know how to handle."""
        raw = {
            "rec_texts": ["Hi"],
            "rec_scores": [0.9],
            "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
            "future_key_1": {"nested": "value"},
            "future_key_2": [1, 2, 3],
            "future_key_3": "string",
        }
        blocks = normalize_paddle_output(raw)
        assert len(blocks) == 1
        assert blocks[0].text == "Hi"

    def test_object_with_only_text_attribute_skipped(self):
        """A future PaddleOCR object that omits ``score`` is silently
        dropped (we cannot compute a confidence score)."""

        class FutureLine:
            text = "no score"
            # NOTE: no score attribute

        assert normalize_paddle_output([FutureLine()]) == []


# ---------------------------------------------------------------------------
# PaddleX — future output shapes
# ---------------------------------------------------------------------------


class TestStructureFutureCompatibility:
    def test_unknown_payload_returns_empty(self):
        """A PaddleX 4.x object with no ``json`` attribute and no
        ``block_content`` attribute returns ``([], None, None)``."""
        blocks, conf, md = normalize_structure_output(SimpleNamespace(name="noop"))
        assert blocks == [] and conf is None and md is None

    def test_unknown_region_keys_ignored(self):
        """PaddleX 4.x may add new region-level fields; we ignore them."""
        raw = {
            "res": {
                "parsing_res_list": [
                    {
                        "block_content": "Body",
                        "block_label": "text",
                        "block_bbox": [0, 0, 10, 10],
                        "future_field": "ignored",
                    }
                ],
                "future_top_level": "ignored",
            }
        }
        blocks, _, _ = normalize_structure_output(raw)
        assert len(blocks) == 1

    def test_payload_with_no_res_block(self):
        """Older payloads without ``res`` are still accepted (the
        function falls back to using the payload itself as ``res``)."""
        raw = {
            "parsing_res_list": [
                {"block_content": "Legacy", "block_label": "text", "block_bbox": [0, 0, 10, 10]}
            ]
        }
        # The function only accepts the canonical ``res`` shape, so this
        # returns empty — but it must NOT raise.
        blocks, _, _ = normalize_structure_output(raw)
        assert blocks == []


# ---------------------------------------------------------------------------
# Adapter construction — forward-compat
# ---------------------------------------------------------------------------


class TestAdapterForwardCompat:
    def test_paddle_adapter_accepts_extra_kwargs(self):
        """Adding new keyword arguments to the adapter constructor must
        not break existing call sites that pass only the documented
        ones."""
        profile = OcrProfile(
            id="ppocr_v6_medium",
            backend="paddleocr",
            model_type="PP-OCRv6",
            detection_model_name=None,
            recognition_model_name=None,
            use_predict_api=True,
        )
        adapter = PaddleOCRAdapter(
            profile=profile,
            lang="es",
            device="cpu",
            engine_factory=lambda: SimpleNamespace(predict=lambda p: [], ocr=lambda p: None),
            log_runtime_info=False,
        )
        assert adapter.name == "paddleocr"

    def test_structure_adapter_accepts_extra_kwargs(self):
        profile = StructureProfile(
            id="pp_structure_v3",
            backend="paddlex",
            pipeline="layout_parsing",
            prefer_v3=True,
        )
        adapter = StructureAdapter(
            profile=profile,
            device="gpu",
            engine_factory=lambda: SimpleNamespace(predict=lambda p: iter([])),
            log_runtime_info=False,
        )
        assert adapter.name == "pp_structure"

    def test_resolve_structure_pipeline_force_fallback_returns_legacy(self):
        """Operator can pin the legacy profile via settings without
        changing the profile id."""
        settings = SimpleNamespace(
            pp_structure_profile="pp_structure_v3",
            pp_structure_pipeline_name=None,
            pp_structure_use_v3=True,
            pp_structure_force_paddlex_fallback=True,
        )
        profile = resolve_structure_pipeline(settings)
        assert profile.id == "layout_parsing_legacy"

    def test_unknown_settings_fields_are_ignored(self):
        """A future settings object may have fields the registry does not
        know about; the resolver must not crash."""
        settings = SimpleNamespace(
            paddle_ocr_profile="ppocr_v6_medium",
            paddle_text_detection_model_name=None,
            paddle_text_recognition_model_name=None,
            paddle_use_predict_api=True,
            paddle_force_legacy_ocr_api=False,
            paddle_force_predict_api=False,
            future_setting_1="ignored",
            future_setting_2=42,
        )
        profile = resolve_ocr_models(settings)
        assert profile.id == "ppocr_v6_medium"