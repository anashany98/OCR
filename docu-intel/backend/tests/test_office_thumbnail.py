from pathlib import Path
from types import SimpleNamespace

from app.services import thumbnail


def test_office_thumbnail_converts_to_temporary_pdf(monkeypatch, tmp_path):
    source = tmp_path / "presupuesto.docx"
    source.write_bytes(b"placeholder")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        output_dir = Path(command[command.index("--outdir") + 1])
        (output_dir / "presupuesto.pdf").write_bytes(b"%PDF-1.4")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(thumbnail.subprocess, "run", fake_run)
    monkeypatch.setattr(
        thumbnail,
        "generate_pdf_thumbnail",
        lambda path, document_hash: Path(f"thumbnails/{document_hash}.jpg"),
    )

    result = thumbnail.generate_office_thumbnail(source, "a" * 64)

    assert result == Path(f"thumbnails/{'a' * 64}.jpg")
    assert captured["command"][:4] == ["soffice", "--headless", "--convert-to", "pdf"]


def test_office_thumbnail_rejects_unsupported_extension(tmp_path):
    assert thumbnail.generate_office_thumbnail(tmp_path / "not-a-word-file.txt", "a" * 64) is None
