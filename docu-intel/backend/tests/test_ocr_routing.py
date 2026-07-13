from pathlib import Path

from app.ocr.routing import manuscript_likelihood


def test_filename_hint_routes_manuscript_without_image_dependencies(tmp_path: Path):
    kind, likelihood = manuscript_likelihood(tmp_path / "nota_manuscrita_obra.jpg")
    assert kind == "manuscript"
    assert likelihood >= 0.75


def test_unknown_filename_fails_open(tmp_path: Path):
    kind, likelihood = manuscript_likelihood(tmp_path / "archivo.jpg")
    assert kind in {"printed_or_unknown", "sketch_or_plan", "photographed_note"}
    assert 0 <= likelihood <= 1
