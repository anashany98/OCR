from pathlib import Path

import pytest

from app.parsers.dwg import DwgConversionError, parse_dwg
from app.parsers.content_router import ContentRoute, classify_content
from app.services.file_security import inspect_file_for_ingestion
from app.parsers.types import ExtractedDocument, ExtractedPage


def test_parse_dwg_converts_a_copy_then_uses_dxf_parser(tmp_path: Path, monkeypatch):
    source = tmp_path / "plan.dwg"
    source.write_bytes(b"AC1032binary-plan")
    converted_paths: list[tuple[Path, Path]] = []

    def fake_convert(original: Path, destination: Path) -> None:
        converted_paths.append((original, destination))
        destination.write_text("converted dxf", encoding="utf-8")

    monkeypatch.setattr("app.parsers.dwg._convert_dwg_to_dxf", fake_convert)
    monkeypatch.setattr(
        "app.parsers.dwg.parse_dxf",
        lambda path, output_dir: ExtractedDocument(pages=[ExtractedPage(page_number=1, text=path.read_text())]),
    )

    extracted = parse_dwg(source, tmp_path / "out")

    assert extracted.text == "converted dxf"
    assert converted_paths[0][0] == source
    assert converted_paths[0][1].suffix == ".dxf"
    assert source.read_bytes() == b"AC1032binary-plan"


def test_parse_dwg_requires_dwg_extension(tmp_path: Path):
    with pytest.raises(DwgConversionError, match="no es .dwg"):
        parse_dwg(tmp_path / "not-a-plan.pdf", tmp_path / "out")


def test_dwg_converter_absence_gives_operator_action(tmp_path: Path, monkeypatch):
    source = tmp_path / "plan.dwg"
    source.write_bytes(b"AC1032binary-plan")
    monkeypatch.setattr("app.parsers.dwg.settings.dwg_converter_path", "")
    monkeypatch.setattr("app.parsers.dwg.shutil.which", lambda _: None)

    with pytest.raises(DwgConversionError, match="DWG_CONVERTER_PATH"):
        parse_dwg(source, tmp_path / "out")


def test_dwg_uses_authenticated_windows_bridge_when_configured(monkeypatch, tmp_path: Path):
    from app.core.config import settings
    from app.parsers import dwg

    source = tmp_path / "plan.dwg"
    source.write_bytes(b"AC1018 fake")
    destination = tmp_path / "plan.dxf"
    calls: dict[str, object] = {}

    class Response:
        status_code = 200
        content = b"0\nSECTION\n0\nEOF\n"
        text = ""

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls.update(kwargs)
        return Response()

    monkeypatch.setattr("app.parsers.dwg.httpx.post", fake_post)
    monkeypatch.setattr(settings, "dwg_converter_bridge_url", "http://host.docker.internal:8789")
    monkeypatch.setattr(settings, "dwg_converter_bridge_token", "x" * 32)

    dwg._convert_dwg_to_dxf(source, destination)

    assert calls["url"] == "http://host.docker.internal:8789/convert"
    assert calls["headers"] == {"X-Docu-Intel-Bridge-Token": "x" * 32}
    assert destination.read_bytes().startswith(b"0\nSECTION")


def test_dwg_is_recognized_as_a_plan_and_requires_its_binary_signature(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allowed_file_extensions", [".dwg"])
    valid = tmp_path / "plan.dwg"
    valid.write_bytes(b"AC1032binary-plan")
    invalid = tmp_path / "renamed.dwg"
    invalid.write_bytes(b"not-a-dwg")

    assert classify_content(valid).route is ContentRoute.STANDARD_OCR
    assert inspect_file_for_ingestion(valid).allowed is True
    assert inspect_file_for_ingestion(invalid).reason == "invalid_dwg_signature"
