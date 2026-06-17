"""Tests for app.ocr.structure_adapter (UPG-4).

Covers:

* CPU refusal (PP-Structure / layout_parsing is GPU-only in
  PaddlePaddle 3.x).
* Normalisation of the canonical ``LayoutParsingResult.json`` payload.
* Normalisation of object-style results (older PaddleX shapes).
* Normalisation of a payload with a markdown export.
* Engine factory injection so the tests never load PaddleX.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ocr.model_registry import StructureProfile
from app.ocr.structure_adapter import StructureAdapter, normalize_structure_output


# ---------------------------------------------------------------------------
# Adapter — construction
# ---------------------------------------------------------------------------


def test_structure_adapter_refuses_cpu():
    with pytest.raises(RuntimeError, match="GPU-only"):
        StructureAdapter(device="cpu")


def test_structure_adapter_accepts_gpu():
    profile = StructureProfile(
        id="pp_structure_v3",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
    )
    adapter = StructureAdapter(
        device="gpu",
        profile=profile,
        engine_factory=lambda: SimpleNamespace(predict=lambda p: []),
        log_runtime_info=False,
    )
    assert adapter.name == "pp_structure"
    assert adapter.profile.id == "pp_structure_v3"


def test_structure_adapter_uses_engine_factory(tmp_path: Path):
    """The factory path is the only one we test (no real PaddleX)."""

    class FakePipeline:
        def __init__(self):
            self.calls = []

        def predict(self, path):
            self.calls.append(path)
            return iter(
                [
                    SimpleNamespace(
                        json={
                            "res": {
                                "parsing_res_list": [
                                    {
                                        "block_bbox": [10, 20, 200, 60],
                                        "block_label": "doc_title",
                                        "block_content": "Title",
                                    }
                                ],
                                "overall_ocr_res": {"rec_scores": [0.9]},
                            }
                        }
                    )
                ]
            )

    profile = StructureProfile(
        id="pp_structure_v3",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
    )
    pipeline = FakePipeline()
    adapter = StructureAdapter(
        device="gpu",
        profile=profile,
        engine_factory=lambda: pipeline,
        log_runtime_info=False,
    )
    image = tmp_path / "img.png"
    result = adapter.run(image)
    assert result.engine == "pp_structure"
    assert result.text == "Title"
    assert result.confidence == 0.9
    assert len(result.blocks) == 1
    assert result.blocks[0].block_type == "doc_title"
    assert pipeline.calls == [str(image)]


def test_structure_adapter_handles_empty_pipeline():
    profile = StructureProfile(
        id="pp_structure_v3",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
    )
    adapter = StructureAdapter(
        device="gpu",
        profile=profile,
        engine_factory=lambda: SimpleNamespace(predict=lambda p: iter([])),
        log_runtime_info=False,
    )
    result = adapter.run(Path("/tmp/img.png"))
    assert result.text == ""
    assert result.blocks == []
    assert result.confidence is None


def test_structure_adapter_pipeline_without_predict_raises():
    profile = StructureProfile(
        id="pp_structure_v3",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
    )
    adapter = StructureAdapter(
        device="gpu",
        profile=profile,
        engine_factory=lambda: SimpleNamespace(),
        log_runtime_info=False,
    )
    with pytest.raises(RuntimeError, match="predict"):
        adapter.run(Path("/tmp/img.png"))


# ---------------------------------------------------------------------------
# normalize_structure_output
# ---------------------------------------------------------------------------


class TestNormalizeStructureOutput:
    def test_none(self):
        blocks, conf, md = normalize_structure_output(None)
        assert blocks == [] and conf is None and md is None

    def test_canonical_layoutparsingresult(self):
        class R:
            json = {
                "res": {
                    "parsing_res_list": [
                        {
                            "block_bbox": [10.0, 20.0, 200.0, 60.0],
                            "block_label": "doc_title",
                            "block_content": "Factura 12345",
                        },
                        {
                            "block_bbox": [10.0, 80.0, 200.0, 110.0],
                            "block_label": "text",
                            "block_content": "Total: 100,00",
                        },
                        {
                            "block_bbox": [10.0, 140.0, 200.0, 180.0],
                            "block_label": "figure",
                            "block_content": "",
                        },
                    ],
                    "overall_ocr_res": {"rec_scores": [0.9, 0.8]},
                    "markdown": {"text": "# Factura 12345"},
                }
            }

        blocks, conf, md = normalize_structure_output(R())
        assert [b.text for b in blocks] == ["Factura 12345", "Total: 100,00"]
        assert [b.block_type for b in blocks] == ["doc_title", "text"]
        assert conf == pytest.approx(0.85)
        assert md == "# Factura 12345"

    def test_object_style_result(self):
        class Line:
            block_content = "Direct"
            block_bbox = [0, 0, 10, 10]
            block_label = "text"

        blocks, conf, md = normalize_structure_output(Line())
        assert len(blocks) == 1
        assert blocks[0].text == "Direct"
        assert blocks[0].bbox == (0.0, 0.0, 10.0, 10.0)
        assert conf is None and md is None

    def test_raw_dict_no_json_attr(self):
        raw = {
            "res": {
                "parsing_res_list": [
                    {
                        "block_content": "Hello",
                        "block_label": "text",
                        "block_bbox": [0, 0, 10, 10],
                    }
                ]
            }
        }
        blocks, conf, md = normalize_structure_output(raw)
        assert len(blocks) == 1 and blocks[0].text == "Hello"

    def test_empty_payload(self):
        class R:
            json = {"res": {"parsing_res_list": []}}

        blocks, conf, md = normalize_structure_output(R())
        assert blocks == [] and conf is None and md is None

    def test_handles_unknown_keys_gracefully(self):
        raw = {
            "res": {
                "parsing_res_list": [
                    {
                        "block_content": "OK",
                        "block_label": "text",
                        "block_bbox": [0, 0, 1, 1],
                        "future_field": "ignored",
                    }
                ],
                "future_top_level": "ignored",
            }
        }
        blocks, conf, md = normalize_structure_output(raw)
        assert len(blocks) == 1

    def test_alternative_payload_keys(self):
        """PaddleX has used different keys over the years; we accept a few."""
        raw = {
            "res": {
                "layout_parsing_res_list": [
                    {"block_content": "A", "block_label": "text", "block_bbox": [0, 0, 1, 1]},
                ]
            }
        }
        blocks, _, _ = normalize_structure_output(raw)
        assert len(blocks) == 1

    def test_markdown_string_at_top_level(self):
        raw = {"res": {"markdown": "# Hello", "parsing_res_list": []}}
        _, _, md = normalize_structure_output(raw)
        assert md == "# Hello"


# ---------------------------------------------------------------------------
# Markdown export toggle
# ---------------------------------------------------------------------------


def test_markdown_export_toggle():
    profile = StructureProfile(
        id="pp_structure_v3",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
    )

    class FakePipeline:
        def predict(self, path):
            return iter(
                [
                    SimpleNamespace(
                        json={
                            "res": {
                                "parsing_res_list": [
                                    {
                                        "block_content": "Body",
                                        "block_label": "text",
                                        "block_bbox": [0, 0, 10, 10],
                                    }
                                ],
                                "markdown": {"text": "# Heading"},
                            }
                        }
                    )
                ]
            )

    adapter_with_md = StructureAdapter(
        device="gpu",
        profile=profile,
        engine_factory=lambda: FakePipeline(),
        export_markdown=True,
        log_runtime_info=False,
    )
    adapter_no_md = StructureAdapter(
        device="gpu",
        profile=profile,
        engine_factory=lambda: FakePipeline(),
        export_markdown=False,
        log_runtime_info=False,
    )

    out_with = adapter_with_md.run(Path("/tmp/img.png"))
    out_without = adapter_no_md.run(Path("/tmp/img.png"))

    assert "# Heading" in out_with.text
    assert "# Heading" not in out_without.text