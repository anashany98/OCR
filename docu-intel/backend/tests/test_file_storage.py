from pathlib import Path

from app.services.file_storage import calculate_sha256, stored_relative_path


def test_calculates_sha256_and_stable_storage_path(tmp_path: Path):
    sample = tmp_path / "factura.pdf"
    sample.write_bytes(b"docu-intel")

    digest = calculate_sha256(sample)
    relative_path = stored_relative_path(digest, ".pdf")

    assert digest == "e7aae9b0b4dbf984a600284a21197ce10a90f4f4c9d7cac7c477fdedd84ac4b5"
    assert relative_path == Path("e7") / f"{digest}.pdf"
