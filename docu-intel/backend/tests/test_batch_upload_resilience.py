from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import UploadFile

from app.api.routes import documents


def test_batch_upload_rolls_back_and_continues_after_a_file_failure(monkeypatch):
    db = Mock()
    user = SimpleNamespace(id=1)
    calls = 0

    def register_once_then_succeed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated database flush failure")
        return (
            SimpleNamespace(id=42, original_filename="second.txt", status="pending"),
            SimpleNamespace(id=99),
        )

    monkeypatch.setattr(documents, "register_upload", register_once_then_succeed)
    files = [
        UploadFile(filename="first.txt", file=BytesIO(b"first")),
        UploadFile(filename="second.txt", file=BytesIO(b"second")),
    ]

    result = documents.upload_batch(files=files, relative_paths="[]", db=db, user=user)

    assert result.uploaded == 1
    assert result.failed == 1
    assert [(item.document_id, item.job_id) for item in result.documents] == [(42, 99)]
    db.rollback.assert_called_once()
    db.commit.assert_called_once()
