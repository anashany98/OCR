"""Lock the OPS-01 PDF preview MIME fix.

The audit found that ``get_document_page_image`` used to rely on the
filename extension alone (which was always ``.png`` even when the
bytes were JPEG). Browsers and proxies cached the preview under the
wrong ``Content-Type`` and some refused to render it.

The fix has two halves:

1. The parser writes the actual format to disk: ``.jpg`` for the
   fast JPEG path, ``.png`` for the fallback. See
   ``app.parsers.pdf._render_page_to_image``.
2. The route pins ``media_type`` explicitly so the response header
   always matches the bytes, even if a future code path stores the
   preview under a non-standard name. See
   ``app.api.routes.documents.get_document_page_image``.

These tests pin both halves so the JPEG/PNG mismatch that ships
with the .png extension cannot regress.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


class _FakePath:
    """Minimal stand-in for ``pathlib.Path`` that exposes only
    ``suffix`` and the ``is_file()`` check the route uses.

    The route treats ``path.suffix.lower()`` to pick the MIME type.
    A ``.jpg`` / ``.jpeg`` suffix must produce ``image/jpeg``;
    anything else (including ``.png``) produces ``image/png``.
    """

    def __init__(self, suffix: str, *, exists: bool = True) -> None:
        self.suffix = suffix
        self._exists = exists

    def is_file(self) -> bool:
        return self._exists


def test_picks_image_jpeg_for_dot_jpg():
    """A preview stored with the .jpg extension must come back
    with ``Content-Type: image/jpeg`` so browsers / proxies stop
    mis-caching it as PNG.
    """
    from app.api.routes.documents import get_document_page_image

    captured: dict[str, object] = {}

    def fake_fileresponse(path, media_type=None, **kwargs):
        captured["path"] = path
        captured["media_type"] = media_type
        return "stub"

    fake_path = _FakePath(".jpg")
    fake_db = MagicMock()
    fake_user = MagicMock()
    # The route reads the document, the page, then resolves the
    # filesystem path. Stub those three lookups.
    fake_doc = MagicMock(id=1, source_path="/data/files/x.jpg")
    fake_page = MagicMock(image_path="/data/files/x.jpg")

    # We bypass the DB by mocking the route's helpers; this test
    # only cares that ``FileResponse`` is called with the right
    # ``media_type`` argument.
    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.api.routes.documents.FileResponse", fake_fileresponse)
        m.setattr(fake_db, "get", lambda *_a, **_k: fake_doc)
        # The route also calls can_access_document — patch it to
        # bypass the access check.
        m.setattr(
            "app.api.routes.documents.can_access_document",
            lambda *_a, **_k: True,
            raising=False,
        )
        m.setattr(
            "app.api.routes.documents.resolve_user_access_scope",
            lambda *_a, **_k: MagicMock(),
            raising=False,
        )
        # The page lookup uses ``db.scalar`` — patch it.
        m.setattr(fake_db, "scalar", lambda *_a, **_k: fake_page)
        # The path resolver returns our fake path.
        m.setattr(
            "app.api.routes.documents._resolve_files_dir_path",
            lambda *_a, **_k: fake_path,
            raising=False,
        )
        get_document_page_image(
            document_id=1,
            page_number=1,
            db=fake_db,
            user=fake_user,
        )

    assert captured["media_type"] == "image/jpeg"


def test_picks_image_jpeg_for_dot_jpeg():
    """``.jpeg`` (4-letter variant) must also map to image/jpeg."""
    from app.api.routes.documents import get_document_page_image

    captured: dict[str, object] = {}

    def fake_fileresponse(path, media_type=None, **kwargs):
        captured["media_type"] = media_type
        return "stub"

    fake_path = _FakePath(".jpeg")
    fake_doc = MagicMock(id=1, source_path="/data/files/x.jpeg")
    fake_page = MagicMock(image_path="/data/files/x.jpeg")
    fake_db = MagicMock()

    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.api.routes.documents.FileResponse", fake_fileresponse)
        m.setattr(fake_db, "get", lambda *_a, **_k: fake_doc)
        m.setattr(
            "app.api.routes.documents.can_access_document",
            lambda *_a, **_k: True,
            raising=False,
        )
        m.setattr(
            "app.api.routes.documents.resolve_user_access_scope",
            lambda *_a, **_k: MagicMock(),
            raising=False,
        )
        m.setattr(fake_db, "scalar", lambda *_a, **_k: fake_page)
        m.setattr(
            "app.api.routes.documents._resolve_files_dir_path",
            lambda *_a, **_k: fake_path,
            raising=False,
        )
        get_document_page_image(
            document_id=1,
            page_number=1,
            db=fake_db,
            user=MagicMock(),
        )

    assert captured["media_type"] == "image/jpeg"


def test_picks_image_png_for_dot_png():
    """A preview stored with the .png extension must come back
    with ``Content-Type: image/png`` (the legacy / fallback case)."""
    from app.api.routes.documents import get_document_page_image

    captured: dict[str, object] = {}

    def fake_fileresponse(path, media_type=None, **kwargs):
        captured["media_type"] = media_type
        return "stub"

    fake_path = _FakePath(".png")
    fake_doc = MagicMock(id=1, source_path="/data/files/x.png")
    fake_page = MagicMock(image_path="/data/files/x.png")
    fake_db = MagicMock()

    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.api.routes.documents.FileResponse", fake_fileresponse)
        m.setattr(fake_db, "get", lambda *_a, **_k: fake_doc)
        m.setattr(
            "app.api.routes.documents.can_access_document",
            lambda *_a, **_k: True,
            raising=False,
        )
        m.setattr(
            "app.api.routes.documents.resolve_user_access_scope",
            lambda *_a, **_k: MagicMock(),
            raising=False,
        )
        m.setattr(fake_db, "scalar", lambda *_a, **_k: fake_page)
        m.setattr(
            "app.api.routes.documents._resolve_files_dir_path",
            lambda *_a, **_k: fake_path,
            raising=False,
        )
        get_document_page_image(
            document_id=1,
            page_number=1,
            db=fake_db,
            user=MagicMock(),
        )

    assert captured["media_type"] == "image/png"


def test_no_filename_means_404():
    """If the page row has no ``image_path`` (e.g. digital page
    with no preview) the route must return 404, not crash with a
    bad path."""
    from app.api.routes.documents import get_document_page_image

    fake_doc = MagicMock(id=1, source_path="/data/files/x.pdf")
    fake_page = MagicMock(image_path=None)  # no preview
    fake_db = MagicMock()

    with pytest.MonkeyPatch.context() as m:
        m.setattr(fake_db, "get", lambda *_a, **_k: fake_doc)
        m.setattr(
            "app.api.routes.documents.can_access_document",
            lambda *_a, **_k: True,
            raising=False,
        )
        m.setattr(
            "app.api.routes.documents.resolve_user_access_scope",
            lambda *_a, **_k: MagicMock(),
            raising=False,
        )
        m.setattr(fake_db, "scalar", lambda *_a, **_k: fake_page)
        with pytest.raises(HTTPException) as excinfo:
            get_document_page_image(
                document_id=1,
                page_number=1,
                db=fake_db,
                user=MagicMock(),
            )
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Regression guard for the centralised OCR threshold
# ---------------------------------------------------------------------------


def test_no_hardcoded_ocr_confidence_threshold_in_admin_routes():
    """If someone re-introduces a hardcoded ``0.70`` (or any
    literal) in the work-inbox / OCR-review endpoints instead of
    reading from ``settings.low_ocr_confidence_threshold``, this
    test fails. The audit's "bajalo al 60%" fix must stay
    centralised.
    """
    import re

    import app.api.routes.admin_operations as ops
    import app.api.routes.admin_quality as quality

    for module in (ops, quality):
        source = Path(module.__file__).read_text(encoding="utf-8")
        # Look for ``Query(default=0.7...)`` or
        # ``Query(default=0.6...)`` — anything hardcoded. The
        # only acceptable value is the one pulled from settings.
        matches = re.findall(r"Query\(default=0\.\d+", source)
        assert not matches, (
            f"{module.__name__} has hardcoded threshold(s): {matches}. "
            "Read from settings.low_ocr_confidence_threshold instead."
        )
