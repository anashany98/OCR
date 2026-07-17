from app.ocr.base import OCRResult
from app.ocr.ovisocr2_output import parse_ovisocr2_output, sanitize_ovisocr2_markdown
from app.services.ocr_decision import decide_ocr_result


def test_output_preserves_markdown_extracts_structures_and_scales_visual_regions():
    parsed = parse_ovisocr2_output(
        "# Presupuesto\n<table><tr><td>42</td></tr></table>\n$$x=1$$\n"
        '<img src="images/bbox_100_200_900_800.jpg" />',
        image_width=1000,
        image_height=500,
    )

    assert parsed.markdown.startswith("# Presupuesto")
    assert {block.block_type for block in parsed.blocks} >= {"text", "table", "formula", "figure"}
    figure = next(block for block in parsed.blocks if block.block_type == "figure")
    assert figure.bbox == (100.0, 100.0, 900.0, 400.0)


def test_output_drops_executable_and_external_html_without_dropping_table():
    clean = sanitize_ovisocr2_markdown(
        '<script>alert(1)</script><table onclick="bad()" style="background:url(x)"><tr><td>ok</td></tr></table>'
        '<img src="https://example.invalid/tracker.png"><img src="file:///host/secret.png">'
    )

    assert "script" not in clean
    assert "onclick" not in clean
    assert "style" not in clean
    assert "https://" not in clean
    assert "file:///" not in clean
    assert "<table" in clean


def test_output_marks_token_truncation_for_review():
    parsed = parse_ovisocr2_output(
        "contenido parcial",
        image_width=10,
        image_height=10,
        finish_reason="length",
    )

    assert "truncated_output" in parsed.warnings


def test_invalid_visual_region_is_not_persisted_as_a_fake_box():
    parsed = parse_ovisocr2_output(
        '<img src="images/bbox_900_1_100_4.jpg" />',
        image_width=100,
        image_height=100,
    )

    assert not [block for block in parsed.blocks if block.block_type == "figure"]
    assert "invalid_visual_region" in parsed.warnings


def test_numeric_conflict_warning_cannot_be_autoaccepted():
    decision = decide_ocr_result(
        OCRResult(text="Factura 999", confidence=None, blocks=[], warnings=["numeric_conflict"]),
        baseline=OCRResult(text="Factura 123", confidence=0.9, blocks=[]),
    )

    assert decision.decision == "review_required"
    assert "numeric_conflict" in decision.reasons


def test_table_structure_conflict_requires_review():
    decision = decide_ocr_result(
        OCRResult(text="<table><tr><td>a</td></tr></table>", confidence=None, blocks=[]),
        baseline=OCRResult(
            text="<table><tr><td>a</td><td>b</td></tr></table>", confidence=0.9, blocks=[]
        ),
    )

    assert decision.decision == "review_required"
    assert "table_structure_conflict" in decision.reasons
