from pathlib import Path

import pytest

from app.parsers.router import UnsupportedDocumentFormatError, parse_document
from app.services.file_security import inspect_file_for_ingestion


@pytest.mark.parametrize("suffix", [".zip", ".rar", ".mp4"])
def test_binary_formats_without_a_parser_are_not_read_as_plain_text(tmp_path: Path, suffix: str):
    binary_file = tmp_path / f"sample{suffix}"
    binary_file.write_bytes(b"\x00\xff\x01\x02not-text")

    with pytest.raises(UnsupportedDocumentFormatError, match="extracción segura"):
        parse_document(binary_file, tmp_path / "out", ocr_engine=None)  # type: ignore[arg-type]


def test_text_file_keeps_plain_text_route(tmp_path: Path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("texto verificable", encoding="utf-8")

    extracted = parse_document(text_file, tmp_path / "out", ocr_engine=None)  # type: ignore[arg-type]

    assert extracted.text == "texto verificable"


def test_msg_is_allowed_only_with_the_compound_file_signature(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allowed_file_extensions", [".msg"])
    valid = tmp_path / "mail.msg"
    valid.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"payload")
    invalid = tmp_path / "renamed.msg"
    invalid.write_bytes(b"plain text")

    assert inspect_file_for_ingestion(valid).allowed is True
    rejected = inspect_file_for_ingestion(invalid)
    assert rejected.allowed is False
    assert rejected.reason == "invalid_msg_signature"
