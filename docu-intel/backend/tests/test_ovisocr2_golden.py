"""Deterministic parser regression tests over non-sensitive golden fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from app.ocr.ovisocr2_output import parse_ovisocr2_output


def test_representative_markdown_golden_fixture_is_preserved_and_structured():
    fixture_path = Path(__file__).parent / "fixtures" / "ovisocr2" / "representative_markdown.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    parsed = parse_ovisocr2_output(
        fixture["markdown"],
        image_width=fixture["image_width"],
        image_height=fixture["image_height"],
    )

    assert parsed.markdown == fixture["markdown"]
    assert {block.block_type for block in parsed.blocks} == set(fixture["expected_types"])
    figure = next(block for block in parsed.blocks if block.block_type == "figure")
    assert figure.bbox == tuple(fixture["expected_bbox"])
