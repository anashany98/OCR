"""Override Starlette's default file-part cap on multipart/form-data.

Starlette's ``MultiPartParser`` (in ``starlette.formparsers``) caps the number
of file parts per request at 1000 by default. The error raised is
``MultiPartException("Too many files. Maximum number of files is 1000.")``,
which FastAPI surfaces as a 400. DocuIntel ingests folders (drag-and-drop or
``webkitdirectory``) that can contain far more files, so we widen the cap
from ``Settings.max_upload_files`` at import time.

We patch the integration point (``Request._get_form``) rather than the
parser itself: that's the single funnel through which FastAPI's ``File(...)``
and ``Form(...)`` dependencies end up calling ``MultiPartParser``. By
overriding the default ``max_files`` at this call site, the rest of
Starlette's parsing pipeline is untouched and the higher cap applies to
every request automatically.

Imported once from ``app.main`` (top of the module, before any router).
"""

from __future__ import annotations

from starlette.requests import Request

from app.core.config import settings

_STARLETTE_DEFAULT_MAX_FILES = 1000


def install() -> int:
    """Replace ``Request._get_form`` so the default ``max_files`` is raised
    from Starlette's 1000 to ``settings.max_upload_files`` whenever the
    caller did not pass an explicit override.

    Returns the value that will be applied (useful for boot-time logging).
    """
    target = max(1, int(settings.max_upload_files))
    original = Request._get_form

    async def _patched_get_form(  # type: ignore[no-untyped-def]
        self,
        *,
        max_files: int | float = _STARLETTE_DEFAULT_MAX_FILES,
        max_fields: int | float = 1000,
        max_part_size: int = 1024 * 1024,
    ):
        if max_files == _STARLETTE_DEFAULT_MAX_FILES:
            max_files = target
        return await original(
            self,
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=max_part_size,
        )

    Request._get_form = _patched_get_form  # type: ignore[method-assign]
    return target


_APPLIED_MAX_FILES = install()
