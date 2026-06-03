from pathlib import Path

from app.services import file_storage
from app.services.file_storage import calculate_sha256, stored_relative_path


def test_calculates_sha256_and_stable_storage_path(tmp_path: Path):
    sample = tmp_path / "factura.pdf"
    sample.write_bytes(b"docu-intel")

    digest = calculate_sha256(sample)
    relative_path = stored_relative_path(digest, ".pdf")

    assert digest == "e7aae9b0b4dbf984a600284a21197ce10a90f4f4c9d7cac7c477fdedd84ac4b5"
    assert relative_path == Path("e7") / f"{digest}.pdf"


def test_copy_to_storage_keeps_independent_copy(tmp_path: Path):
    source = tmp_path / "source.pdf"
    files_dir = tmp_path / "files"
    source.write_bytes(b"original")

    relative_path = file_storage.copy_to_storage(source, files_dir, "a" * 64, ".pdf", strategy="copy")
    stored = files_dir / relative_path

    assert stored.read_bytes() == b"original"

    source.write_bytes(b"mutated")

    assert stored.read_bytes() == b"original"


def test_hardlink_strategy_uses_os_link_when_available(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.pdf"
    files_dir = tmp_path / "files"
    source.write_bytes(b"linked")

    calls: list[tuple[Path, Path]] = []

    def fake_link(src, dst):
        calls.append((Path(src), Path(dst)))
        dst.write_bytes(Path(src).read_bytes())

    monkeypatch.setattr(file_storage.os, "link", fake_link)

    relative_path = file_storage.copy_to_storage(source, files_dir, "b" * 64, ".pdf", strategy="hardlink")
    stored = files_dir / relative_path

    assert calls == [(source, stored)]
    assert stored.read_bytes() == b"linked"
