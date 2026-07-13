from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.services import thumbnail


def test_eml_thumbnail_and_preview_are_readable_jpegs(tmp_path, monkeypatch):
    source = tmp_path / "aviso.eml"
    source.write_bytes(
        b"From: obra@example.test\nSubject: Visita de obra\nDate: Tue, 7 Jul 2026 10:00:00 +0000\n"
        b"Content-Type: text/plain; charset=utf-8\n\nLa visita queda confirmada para manana."
    )
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    monkeypatch.setattr(thumbnail, "THUMBNAIL_DIR", tmp_path / "thumbnails")
    monkeypatch.setattr(thumbnail, "PREVIEW_DIR", tmp_path / "previews")

    thumb = thumbnail.generate_eml_thumbnail(source, "a" * 64)
    preview = thumbnail.generate_eml_preview(source, "b" * 64)

    assert thumb == Path(f"thumbnails/{'a' * 64}.jpg")
    assert preview == Path(f"previews/{'b' * 64}.jpg")
    assert Image.open(tmp_path / thumb).format == "JPEG"
    assert Image.open(tmp_path / preview).size == thumbnail.PREVIEW_SIZE


def test_cad_preview_converts_dwg_in_private_workspace(tmp_path, monkeypatch):
    source = tmp_path / "plano.dwg"
    source.write_bytes(b"dwg-placeholder")
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    monkeypatch.setattr(thumbnail, "PREVIEW_DIR", tmp_path / "previews")
    seen: dict[str, Path] = {}

    def fake_convert(input_path: Path, destination: Path) -> None:
        seen["input"] = input_path
        destination.write_text("fake dxf")

    def fake_render(dxf_path: Path, output_path: Path, size: tuple[int, int]) -> bool:
        seen["dxf"] = dxf_path
        Image.new("RGB", size, "white").save(output_path, "JPEG")
        return True

    monkeypatch.setattr("app.parsers.dwg._convert_dwg_to_dxf", fake_convert)
    monkeypatch.setattr(thumbnail, "_render_cad_dxf_to_image", fake_render)

    preview = thumbnail.generate_cad_preview(source, "c" * 64)

    assert preview == Path(f"previews/{'c' * 64}.jpg")
    assert seen["input"] == source
    assert seen["dxf"].suffix == ".dxf"
    assert Image.open(tmp_path / preview).size == thumbnail.PREVIEW_SIZE


def test_dxf_preview_renders_geometry_and_text(tmp_path, monkeypatch):
    import ezdxf

    source = tmp_path / "plano.dxf"
    document = ezdxf.new()
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (100, 0))
    modelspace.add_line((100, 0), (100, 50))
    modelspace.add_circle((40, 25), 10)
    modelspace.add_text("RECEPCION", dxfattribs={"height": 4, "insert": (15, 20)})
    document.saveas(source)
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    monkeypatch.setattr(thumbnail, "PREVIEW_DIR", tmp_path / "previews")

    preview = thumbnail.generate_cad_preview(source, "d" * 64)

    assert preview == Path(f"previews/{'d' * 64}.jpg")
    image = Image.open(tmp_path / preview)
    assert image.size == thumbnail.PREVIEW_SIZE
    assert image.getbbox() is not None
